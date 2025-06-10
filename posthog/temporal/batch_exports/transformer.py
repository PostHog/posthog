import gzip
import json
from collections.abc import AsyncGenerator
from io import BytesIO

import brotli
import pyarrow as pa
import pyarrow.parquet as pq


class StreamTransformer:
    """Transforms PyArrow RecordBatches to different formats with compression"""

    def __init__(self, output_format: str, output_compression: str = None):
        self.output_format = output_format.lower()
        self.output_compression = output_compression.lower() if output_compression else None

        # For Parquet, we need to handle schema and batching
        self.parquet_writer = None
        self.parquet_buffer = None
        self.parquet_schema = None

    async def transform_batch(self, batch: pa.RecordBatch) -> AsyncGenerator[bytes, None]:
        """Transform a single batch and yield compressed bytes"""
        if self.output_format == "parquet":
            async for chunk in self._write_parquet_batch(batch):
                yield chunk
        elif self.output_format == "jsonl":
            chunk = await self._write_jsonl_batch(batch)
            if chunk:
                yield chunk
        else:
            raise ValueError(f"Unsupported output format: {self.output_format}")

    async def _write_parquet_batch(self, batch: pa.RecordBatch) -> AsyncGenerator[bytes, None]:
        """Handle Parquet format - accumulate batches and write periodically"""
        if self.parquet_schema is None:
            self.parquet_schema = batch.schema
            self.parquet_buffer = BytesIO()
            self.parquet_writer = pq.ParquetWriter(self.parquet_buffer, self.parquet_schema)

        # Write the batch
        self.parquet_writer.write_batch(batch)

        # For streaming, we could flush every N batches or after certain size
        # For now, we'll flush after each batch to maintain streaming behavior
        # In production, you might want to batch multiple RecordBatches

        # Get current buffer content
        current_pos = self.parquet_buffer.tell()
        if current_pos > 1024 * 1024:  # Flush every 1MB
            self.parquet_buffer.seek(0)
            data = self.parquet_buffer.read()
            compressed_data = await self._compress_data(data)

            # Reset buffer and writer
            self.parquet_buffer = BytesIO()
            self.parquet_writer = pq.ParquetWriter(self.parquet_buffer, self.parquet_schema)

            yield compressed_data

    async def _write_jsonl_batch(self, batch: pa.RecordBatch) -> bytes:
        """Convert RecordBatch to JSONL format"""
        # Convert to pandas for easy JSON serialization
        df = batch.to_pandas()

        # Convert to JSONL
        jsonl_lines = []
        for _, row in df.iterrows():
            jsonl_lines.append(json.dumps(row.to_dict(), default=str))

        jsonl_data = "\n".join(jsonl_lines) + "\n"
        return await self._compress_data(jsonl_data.encode("utf-8"))

    async def _compress_data(self, data: bytes) -> bytes:
        """Apply compression to data"""
        if not self.output_compression:
            return data
        elif self.output_compression == "gzip":
            return gzip.compress(data)
        elif self.output_compression == "brotli":
            return brotli.compress(data)
        else:
            raise ValueError(f"Unsupported compression: {self.output_compression}")

    async def finalize(self) -> AsyncGenerator[bytes, None]:
        """Finalize and yield any remaining data"""
        if self.output_format == "parquet" and self.parquet_writer:
            self.parquet_writer.close()

            # Get final data
            self.parquet_buffer.seek(0)
            final_data = self.parquet_buffer.read()
            if final_data:
                compressed_data = await self._compress_data(final_data)
                yield compressed_data

            # Cleanup
            self.parquet_buffer.close()
            self.parquet_writer = None
            self.parquet_buffer = None
