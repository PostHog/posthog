#!/usr/bin/env python3

import os

# Worker Configuration
# Number of worker processes to spawn. Each worker handles requests independently.
# Default: 4 for production workloads. Scale based on CPU cores available.
workers = int(os.getenv("GRANIAN_WORKERS", "4"))

# Threading Configuration
# Number of threads per worker for handling concurrent requests within a worker.
# Default: 2 to balance concurrency without excessive context switching.
threads = int(os.getenv("GRANIAN_THREADS", "2"))

# Threading Mode
# "mt" enables multi-threading, allowing each worker to handle multiple requests concurrently.
# Alternatives: "workers" (multi-process only, no threading)
threading_mode = os.getenv("GRANIAN_THREADING_MODE", "mt")

# Event Loop
# "uvloop" provides better performance than asyncio's default event loop.
# Alternatives: "asyncio" (standard library, broader compatibility)
loop = os.getenv("GRANIAN_LOOP", "uvloop")

# Backpressure Limit
# Maximum number of requests that can be queued per worker before new connections are rejected.
# Prevents memory exhaustion under extreme load. Set to 1000 to handle traffic spikes
# while maintaining bounded resource usage.
backpressure = int(os.getenv("GRANIAN_BACKPRESSURE", "1000"))

# Backlog Size
# Maximum number of pending connections in the OS socket queue.
# Higher values allow the server to accept more connections during traffic bursts
# before clients see connection refused errors.
backlog = int(os.getenv("GRANIAN_BACKLOG", "1000"))

# HTTP Configuration
# Maximum allowed size for HTTP request headers in bytes.
# Default: 16KB should handle most applications. Increase if using large cookies/tokens.
http1_buffer_size = int(os.getenv("GRANIAN_HTTP1_BUFFER_SIZE", "16384"))

# Keep-alive timeout in seconds for idle connections.
# Default: 5 seconds balances connection reuse with resource cleanup.
http1_keep_alive = int(os.getenv("GRANIAN_HTTP1_KEEP_ALIVE", "5"))

# Maximum number of pipelined requests per connection.
# Default: 1 (no pipelining) for simpler connection management and better compatibility.
http1_pipeline_flush = int(os.getenv("GRANIAN_HTTP1_PIPELINE_FLUSH", "1"))

# Websocket Configuration
# Maximum size for websocket messages in bytes.
# Default: 16MB for typical real-time data without excessive memory usage.
websockets_max_size = int(os.getenv("GRANIAN_WEBSOCKETS_MAX_SIZE", str(16 * 1024 * 1024)))

# Logging
# Log level for server output. Options: critical, error, warning, info, debug
log_level = os.getenv("GRANIAN_LOG_LEVEL", "info")

# Enable access logs for HTTP requests.
# Default: False in production to reduce I/O overhead. Enable for debugging.
access_log = os.getenv("GRANIAN_ACCESS_LOG", "false").lower() == "true"

# Binding Configuration
# Interface to bind the server to. Use "0.0.0.0" for all interfaces in containers.
interface = os.getenv("GRANIAN_INTERFACE", "0.0.0.0")

# Port to listen on for HTTP traffic.
port = int(os.getenv("GRANIAN_PORT", "8000"))

# Process Management
# Enable respawn of workers that crash or exit unexpectedly.
# Default: True to maintain worker pool size under failures.
respawn_failed_workers = os.getenv("GRANIAN_RESPAWN_FAILED_WORKERS", "true").lower() == "true"

# Interval in seconds between worker respawn attempts after failures.
# Default: 5 seconds to avoid rapid restart loops.
respawn_interval = int(os.getenv("GRANIAN_RESPAWN_INTERVAL", "5"))

# Graceful Shutdown
# Maximum time in seconds to wait for graceful shutdown before forcing termination.
# Default: 30 seconds allows in-flight requests to complete.
graceful_timeout = int(os.getenv("GRANIAN_GRACEFUL_TIMEOUT", "30"))
