package main

import (
	"bufio"
	"bytes"
	"compress/gzip"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/klauspost/compress/zstd"
	"github.com/pierrec/lz4/v4"
)

const maxDecompressedSize = 64 << 20
const maxCompressedSize = 65 << 20

type processor struct {
	maxOutput  int
	zstd       *zstd.Decoder
	gzip       *gzip.Reader
	lz4        *lz4.Reader
	input      bytes.Reader
	output     bytes.Buffer
	zstdOutput []byte
	lz4Block   []byte
}

func newProcessor(maxOutput int) (*processor, error) {
	decoder, err := zstd.NewReader(nil,
		zstd.WithDecoderConcurrency(1),
		zstd.WithDecoderMaxMemory(uint64(maxOutput)),
	)
	if err != nil {
		return nil, fmt.Errorf("create ZSTD decoder: %w", err)
	}
	return &processor{maxOutput: maxOutput, zstd: decoder, lz4: lz4.NewReader(nil)}, nil
}

func (p *processor) close() {
	p.zstd.Close()
}

func (p *processor) decompress(data []byte, codec string) ([]byte, error) {
	if len(data) == 0 {
		return nil, errors.New("empty compressed data: expected a compression frame or block")
	}
	if codec == "" {
		var err error
		codec, err = detectCodec(data)
		if err != nil {
			return nil, err
		}
	}
	p.input.Reset(data)

	switch {
	case strings.EqualFold(codec, "GZIP"):
		var err error
		if p.gzip == nil {
			p.gzip, err = gzip.NewReader(&p.input)
		} else {
			err = p.gzip.Reset(&p.input)
		}
		if err != nil {
			return nil, fmt.Errorf("invalid GZIP stream: %w", err)
		}
		return p.readLimited(p.gzip)
	case strings.EqualFold(codec, "ZSTD"):
		var err error
		p.zstdOutput, err = p.zstd.DecodeAll(data, p.zstdOutput[:0])
		if err != nil {
			return nil, fmt.Errorf("invalid ZSTD stream: %w", err)
		}
		return p.zstdOutput, nil
	case strings.EqualFold(codec, "LZ4"):
		if err := validateLZ4Frames(data); err != nil {
			return nil, fmt.Errorf("invalid LZ4 stream: %w", err)
		}
		p.lz4.Reset(&p.input)
		return p.readLimited(p.lz4)
	case strings.EqualFold(codec, "LZ4SIZEPREFIXED"):
		// Capture's replay envelope is a little-endian size followed by a raw block.
		if len(data) < 5 {
			return nil, errors.New("truncated LZ4SizePrefixed envelope")
		}
		size := uint64(binary.LittleEndian.Uint32(data[:4]))
		if size > uint64(p.maxOutput) {
			return nil, fmt.Errorf("decompressed size exceeds %d bytes", p.maxOutput)
		}
		p.lz4Block = slices.Grow(p.lz4Block[:0], int(size))[:int(size)]
		n, err := lz4.UncompressBlock(data[4:], p.lz4Block)
		if err != nil || n != int(size) {
			return nil, fmt.Errorf("invalid LZ4SizePrefixed block: decoded %d bytes, expected %d (error: %v)", n, size, err)
		}
		return p.lz4Block[:n], nil
	case strings.EqualFold(codec, "LZ4BLOCK"):
		// ponytail: raw blocks omit their size; use the cap, prefer LZ4SizePrefixed for smaller buffers.
		p.lz4Block = slices.Grow(p.lz4Block[:0], p.maxOutput)[:p.maxOutput]
		n, err := lz4.UncompressBlock(data, p.lz4Block)
		if err != nil {
			return nil, fmt.Errorf("invalid LZ4Block or decompressed size exceeds %d bytes: %w", p.maxOutput, err)
		}
		return p.lz4Block[:n], nil
	default:
		return nil, fmt.Errorf("unsupported compression codec %q", codec)
	}
}

func validateLZ4Frames(data []byte) error {
	// The LZ4 reader treats EOF at some header/block boundaries as success, even without an end mark.
	for len(data) > 0 {
		if len(data) < 4 {
			return io.ErrUnexpectedEOF
		}
		magic := binary.LittleEndian.Uint32(data)
		if magic&0xfffffff0 == 0x184d2a50 {
			if len(data) < 8 {
				return io.ErrUnexpectedEOF
			}
			size := uint64(binary.LittleEndian.Uint32(data[4:])) + 8
			if size > uint64(len(data)) {
				return io.ErrUnexpectedEOF
			}
			data = data[int(size):]
			continue
		}
		if magic != 0x184d2204 {
			return errors.New("expected a standard LZ4 frame")
		}
		if len(data) < 7 {
			return io.ErrUnexpectedEOF
		}
		flags := data[4]
		headerSize := 7
		if flags&0x08 != 0 {
			headerSize += 8
		}
		if flags&0x01 != 0 {
			headerSize += 4
		}
		if len(data) < headerSize {
			return io.ErrUnexpectedEOF
		}
		data = data[headerSize:]
		for {
			if len(data) < 4 {
				return io.ErrUnexpectedEOF
			}
			block := binary.LittleEndian.Uint32(data)
			data = data[4:]
			size := uint64(block & 0x7fffffff)
			if (block == 0 && flags&0x04 != 0) || (block != 0 && flags&0x10 != 0) {
				size += 4
			}
			if size > uint64(len(data)) {
				return io.ErrUnexpectedEOF
			}
			data = data[int(size):]
			if block == 0 {
				break
			}
		}
	}
	return nil
}

func (p *processor) readLimited(reader io.Reader) ([]byte, error) {
	p.output.Reset()
	n, err := io.CopyN(&p.output, reader, int64(p.maxOutput)+1)
	if n > int64(p.maxOutput) {
		return nil, fmt.Errorf("decompressed size exceeds %d bytes", p.maxOutput)
	}
	if err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("decompression failed: %w", err)
	}
	return p.output.Bytes(), nil
}

func detectCodec(data []byte) (string, error) {
	remaining := data
	for len(remaining) >= 8 && binary.LittleEndian.Uint32(remaining[:4])&0xfffffff0 == 0x184d2a50 {
		skip := uint64(binary.LittleEndian.Uint32(remaining[4:8])) + 8
		if skip > uint64(len(remaining)) {
			return "", errors.New("truncated skippable compression frame")
		}
		remaining = remaining[int(skip):]
	}

	switch {
	case len(remaining) >= 3 && bytes.Equal(remaining[:3], []byte{0x1f, 0x8b, 0x08}):
		return "GZIP", nil
	case len(remaining) >= 4 && bytes.Equal(remaining[:4], []byte{0x28, 0xb5, 0x2f, 0xfd}):
		return "ZSTD", nil
	case len(remaining) >= 4 && bytes.Equal(remaining[:4], []byte{0x04, 0x22, 0x4d, 0x18}):
		return "LZ4", nil
	default:
		return "", errors.New("cannot detect compression codec from frame header")
	}
}

func readString(reader *bufio.Reader, buf []byte, maxSize int) ([]byte, error) {
	length, err := binary.ReadUvarint(reader)
	if err != nil {
		return nil, err
	}
	if length > uint64(maxSize) {
		return nil, fmt.Errorf("RowBinary string length %d exceeds %d bytes", length, maxSize)
	}
	value := slices.Grow(buf[:0], int(length))[:int(length)]
	if _, err := io.ReadFull(reader, value); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, io.ErrUnexpectedEOF
		}
		return nil, err
	}
	return value, nil
}

func writeString(writer *bufio.Writer, value []byte) error {
	var length [binary.MaxVarintLen64]byte
	n := binary.PutUvarint(length[:], uint64(len(value)))
	if _, err := writer.Write(length[:n]); err != nil {
		return err
	}
	_, err := writer.Write(value)
	return err
}

func run(input io.Reader, output io.Writer, maxOutput int) error {
	proc, err := newProcessor(maxOutput)
	if err != nil {
		return err
	}
	defer proc.close()

	reader := bufio.NewReaderSize(input, 64*1024)
	writer := bufio.NewWriterSize(output, 64*1024)
	var data, codec []byte
	for {
		// ClickHouse sends an ASCII row count even when the rows use RowBinary.
		header, err := reader.ReadSlice('\n')
		if err == io.EOF && len(header) == 0 {
			return nil
		}
		if err != nil {
			return fmt.Errorf("read chunk header: %w", err)
		}
		rows, err := strconv.ParseUint(string(header[:len(header)-1]), 10, 64)
		if err != nil {
			return fmt.Errorf("invalid chunk header: %w", err)
		}
		for range rows {
			data, err = readString(reader, data, maxCompressedSize)
			if err != nil {
				return fmt.Errorf("read compressed data: %w", err)
			}
			codec, err = readString(reader, codec, 32)
			if err != nil {
				return fmt.Errorf("read codec: %w", err)
			}
			decompressed, err := proc.decompress(data, string(codec))
			if err != nil {
				return err
			}
			if err := writeString(writer, decompressed); err != nil {
				return fmt.Errorf("write decompressed data: %w", err)
			}
		}
		if err := writer.Flush(); err != nil {
			return fmt.Errorf("flush chunk: %w", err)
		}
	}
}

func main() {
	if err := run(os.Stdin, os.Stdout, maxDecompressedSize); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
