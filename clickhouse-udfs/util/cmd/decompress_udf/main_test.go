package main

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"io"
	"strings"
	"testing"

	"github.com/klauspost/compress/zstd"
	"github.com/pierrec/lz4/v4"
)

func TestDecompress(t *testing.T) {
	input := []byte{'h', 'i', 0, '\n', '\t', 0xff}
	fixtures := compressedFixtures(t, input)
	proc, err := newProcessor(1024)
	if err != nil {
		t.Fatal(err)
	}
	defer proc.close()

	for codec, compressed := range fixtures {
		for _, requested := range []string{codec, strings.ToLower(codec), strings.ToUpper(codec), ""} {
			if (codec == "LZ4Block" || codec == "LZ4SizePrefixed") && requested == "" {
				continue
			}
			got, err := proc.decompress(compressed, requested)
			if err != nil {
				t.Fatalf("decompress(%s, %q): %v", codec, requested, err)
			}
			if !bytes.Equal(got, input) {
				t.Fatalf("decompress(%s, %q) = %x, want %x", codec, requested, got, input)
			}
		}
	}

	for codec, compressed := range compressedFixtures(t, nil) {
		if codec == "LZ4Block" || codec == "LZ4SizePrefixed" {
			continue
		}
		got, err := proc.decompress(compressed, "")
		if err != nil || len(got) != 0 {
			t.Fatalf("decompress empty %s = %x, %v", codec, got, err)
		}
	}
}

func TestDecompressFailsFast(t *testing.T) {
	fixtures := compressedFixtures(t, []byte("hello"))
	proc, err := newProcessor(4)
	if err != nil {
		t.Fatal(err)
	}
	defer proc.close()

	tests := []struct {
		name  string
		data  []byte
		codec string
	}{
		{"unknown header", []byte("plain"), ""},
		{"raw block detection", fixtures["LZ4Block"], ""},
		{"unsupported codec", fixtures["GZIP"], "SNAPPY"},
		{"codec mismatch", fixtures["GZIP"], "ZSTD"},
		{"output limit", fixtures["GZIP"], "GZIP"},
		{"truncated stream", fixtures["ZSTD"][:5], "ZSTD"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			if _, err := proc.decompress(test.data, test.codec); err == nil {
				t.Fatal("expected an error")
			}
		})
	}
}

func TestRowBinaryTransport(t *testing.T) {
	value := bytes.Repeat([]byte{'a', '\n', 0, 0xff}, 20*1024)
	fixtures := compressedFixtures(t, value)
	var input bytes.Buffer
	writer := bufio.NewWriter(&input)
	for _, codec := range []string{"GZIP", "ZSTD", "LZ4", "LZ4Block", "LZ4SizePrefixed"} {
		fmt.Fprint(writer, "1\n")
		if err := writeString(writer, fixtures[codec]); err != nil {
			t.Fatal(err)
		}
		if err := writeString(writer, []byte(codec)); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Flush(); err != nil {
		t.Fatal(err)
	}

	var output bytes.Buffer
	if err := run(&input, &output, len(value)); err != nil {
		t.Fatal(err)
	}
	reader := bufio.NewReader(&output)
	for range 5 {
		got, err := readString(reader, nil, len(value))
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(got, value) {
			t.Fatalf("got %x, want %x", got, value)
		}
	}
	if _, err := reader.ReadByte(); err != io.EOF {
		t.Fatalf("unexpected output after final row: %v", err)
	}
}

func TestDetectCodecSkipsMetadataFrame(t *testing.T) {
	fixtures := compressedFixtures(t, []byte("hello"))
	proc, err := newProcessor(1024)
	if err != nil {
		t.Fatal(err)
	}
	defer proc.close()
	for _, codec := range []string{"ZSTD", "LZ4"} {
		data := append([]byte{0x50, 0x2a, 0x4d, 0x18, 0x03, 0, 0, 0, 'a', 'b', 'c'}, fixtures[codec]...)
		if got, err := detectCodec(data); err != nil || got != codec {
			t.Fatalf("detectCodec() = %q, %v, want %s", got, err, codec)
		}
		if got, err := proc.decompress(data, ""); err != nil || string(got) != "hello" {
			t.Fatalf("decompress(%s) = %q, %v", codec, got, err)
		}
	}
}

func compressedFixtures(t testing.TB, input []byte) map[string][]byte {
	t.Helper()
	fixtures := make(map[string][]byte)

	var gzipData bytes.Buffer
	gzipWriter := gzip.NewWriter(&gzipData)
	if _, err := gzipWriter.Write(input); err != nil {
		t.Fatal(err)
	}
	if err := gzipWriter.Close(); err != nil {
		t.Fatal(err)
	}
	fixtures["GZIP"] = gzipData.Bytes()

	zstdWriter, err := zstd.NewWriter(nil, zstd.WithEncoderConcurrency(1), zstd.WithZeroFrames(true))
	if err != nil {
		t.Fatal(err)
	}
	fixtures["ZSTD"] = zstdWriter.EncodeAll(input, nil)
	zstdWriter.Close()

	var lz4Data bytes.Buffer
	lz4Writer := lz4.NewWriter(&lz4Data)
	if _, err := lz4Writer.Write(input); err != nil {
		t.Fatal(err)
	}
	if err := lz4Writer.Close(); err != nil {
		t.Fatal(err)
	}
	fixtures["LZ4"] = lz4Data.Bytes()

	block := make([]byte, lz4.CompressBlockBound(len(input)))
	n, err := lz4.CompressBlock(input, block, nil)
	if err != nil {
		t.Fatal(err)
	}
	if n == 0 {
		t.Fatalf("test input is not compressible as an LZ4 block: %s", hex.EncodeToString(input))
	}
	fixtures["LZ4Block"] = block[:n]
	fixtures["LZ4SizePrefixed"] = append(binary.LittleEndian.AppendUint32(nil, uint32(len(input))), block[:n]...)
	return fixtures
}

func TestChunkFlushedBeforeNextInput(t *testing.T) {
	input, send := io.Pipe()
	output, receive := io.Pipe()
	defer input.Close()
	defer send.Close()
	defer output.Close()
	defer receive.Close()
	done := make(chan error, 1)
	go func() { done <- run(input, receive, 1024) }()
	reader := bufio.NewReader(output)
	fixtures := compressedFixtures(t, []byte("hello\x00\n\xff"))
	for _, rows := range []int{1, 3, 2} {
		var chunk bytes.Buffer
		fmt.Fprintf(&chunk, "%d\n", rows)
		writer := bufio.NewWriter(&chunk)
		for range rows {
			if err := writeString(writer, fixtures["GZIP"]); err != nil {
				t.Fatal(err)
			}
			if err := writeString(writer, []byte("gzip")); err != nil {
				t.Fatal(err)
			}
		}
		if err := writer.Flush(); err != nil {
			t.Fatal(err)
		}
		if _, err := send.Write(chunk.Bytes()); err != nil {
			t.Fatal(err)
		}
		for range rows {
			got, err := readString(reader, nil, 1024)
			if err != nil || string(got) != "hello\x00\n\xff" {
				t.Fatalf("got %q, %v", got, err)
			}
		}
	}
	send.Close()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
}

func TestDecompressBoundaries(t *testing.T) {
	value := bytes.Repeat([]byte("abcd"), 1024)
	fixtures := compressedFixtures(t, value)
	for codec, data := range fixtures {
		t.Run(codec, func(t *testing.T) {
			proc, err := newProcessor(len(value))
			if err != nil {
				t.Fatal(err)
			}
			defer proc.close()
			for _, bad := range [][]byte{nil, data[:len(data)-1], []byte("garbage")} {
				if _, err := proc.decompress(bad, codec); err == nil {
					t.Fatalf("accepted invalid input %x", bad)
				}
			}
			if codec == "GZIP" || codec == "ZSTD" || codec == "LZ4" {
				for end := 1; end < len(data); end++ {
					if _, err := proc.decompress(data[:end], codec); err == nil {
						t.Fatalf("accepted truncated frame of length %d", end)
					}
				}
				if _, err := proc.decompress(append(bytes.Clone(data), data...), codec); err == nil {
					t.Fatal("accepted concatenated frames exceeding the output limit")
				}
			}
			for range 2 {
				got, err := proc.decompress(data, codec)
				if err != nil || !bytes.Equal(got, value) {
					t.Fatalf("exact limit: %v", err)
				}
			}
			limited, err := newProcessor(len(value) - 1)
			if err != nil {
				t.Fatal(err)
			}
			defer limited.close()
			if _, err := limited.decompress(data, codec); err == nil {
				t.Fatal("accepted oversized output")
			}
		})
	}
	proc, err := newProcessor(len(value) * 2)
	if err != nil {
		t.Fatal(err)
	}
	defer proc.close()
	for _, codec := range []string{"GZIP", "ZSTD", "LZ4"} {
		data := append(bytes.Clone(fixtures[codec]), fixtures[codec]...)
		got, err := proc.decompress(data, codec)
		if err != nil || !bytes.Equal(got, bytes.Repeat(value, 2)) {
			t.Fatalf("concatenated %s: %v", codec, err)
		}
		data[len(data)-1] ^= 0xff
		if _, err := proc.decompress(data, codec); err == nil {
			t.Fatalf("accepted corrupt %s checksum", codec)
		}
	}
	for _, size := range []uint32{1, uint32(len(value) + 1), uint32(maxDecompressedSize + 1)} {
		data := bytes.Clone(fixtures["LZ4SizePrefixed"])
		binary.LittleEndian.PutUint32(data, size)
		if _, err := proc.decompress(data, "LZ4SizePrefixed"); err == nil {
			t.Fatalf("accepted incorrect size %d", size)
		}
	}
	var frame bytes.Buffer
	writer := lz4.NewWriter(&frame)
	if err := writer.Apply(lz4.ChecksumOption(false), lz4.BlockChecksumOption(true), lz4.SizeOption(uint64(len(value)))); err != nil {
		t.Fatal(err)
	}
	if _, err := writer.Write(value); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if got, err := proc.decompress(frame.Bytes(), "LZ4"); err != nil || !bytes.Equal(got, value) {
		t.Fatalf("LZ4 with size and block checksum: %v", err)
	}
	for end := 0; end < frame.Len(); end++ {
		data := append(bytes.Clone(fixtures["LZ4"]), frame.Bytes()[:end]...)
		if end > 0 {
			if _, err := proc.decompress(data, "LZ4"); err == nil {
				t.Fatalf("accepted truncated second LZ4 frame at %d", end)
			}
		}
	}
}

func TestInvalidChunkTransport(t *testing.T) {
	for _, input := range [][]byte{
		[]byte("1"), []byte("-1\n"), []byte("x\n"), []byte("1\n"), []byte("1\n\x80"),
		[]byte("1\n\x01"), []byte("1\n\x00"),
		append([]byte("1\n"), binary.AppendUvarint(nil, uint64(maxCompressedSize+1))...),
		append([]byte("1\n\x00"), binary.AppendUvarint(nil, 33)...),
	} {
		if err := run(bytes.NewReader(input), io.Discard, 1024); err == nil {
			t.Fatalf("accepted truncated or invalid transport %x", input)
		}
	}
}

func BenchmarkDecompress(b *testing.B) {
	for _, size := range []int{1024, 64 * 1024} {
		value := bytes.Repeat([]byte(`{"event":"example","properties":{"path":"/example","value":123}}`), size/64+1)[:size]
		fixtures := compressedFixtures(b, value)
		for codec, data := range fixtures {
			b.Run(fmt.Sprintf("%s/%d", codec, size), func(b *testing.B) {
				proc, err := newProcessor(maxDecompressedSize)
				if err != nil {
					b.Fatal(err)
				}
				defer proc.close()
				if _, err := proc.decompress(data, codec); err != nil {
					b.Fatal(err)
				}
				b.SetBytes(int64(len(value)))
				b.ReportAllocs()
				b.ResetTimer()
				for range b.N {
					got, err := proc.decompress(data, codec)
					if err != nil || len(got) != len(value) {
						b.Fatalf("decompress: %v", err)
					}
				}
			})
		}
	}
}
