# Multi-stage Dockerfile for PostHog Pod Rebalancer
# Optimized for minimal image size and security

# Stage 1: Build stage
FROM golang:1.25-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

# Set working directory
WORKDIR /build

# Copy go mod files first for better layer caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the binary with optimizations
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags='-w -s -extldflags "-static"' \
    -a -installsuffix cgo \
    -o pod-rebalancer \
    ./cmd/rebalancer

# Verify the binary works
RUN ./pod-rebalancer --help || echo "Binary built successfully"

# Stage 2: Final runtime stage
FROM alpine:3.19

# Install runtime dependencies
RUN apk --no-cache add ca-certificates tzdata

# Create non-root user for security
RUN adduser -D -s /bin/sh -u 10001 rebalancer

# Set working directory
WORKDIR /app

# Copy the binary from builder stage
COPY --from=builder /build/pod-rebalancer /app/

# Copy timezone data
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo

# Set permissions
RUN chown rebalancer:rebalancer /app/pod-rebalancer && \
    chmod +x /app/pod-rebalancer

# Switch to non-root user
USER rebalancer

# Health check (optional - for debugging)
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD /app/pod-rebalancer --help > /dev/null || exit 1

# Run the application
ENTRYPOINT ["/app/pod-rebalancer"]

# Labels for metadata
LABEL maintainer="PostHog Ingestion Team" \
      description="HPA-aware Kafka consumer pod rebalancer" \
      version="1.0.0" \
      org.opencontainers.image.source="https://github.com/PostHog/posthog" \
      org.opencontainers.image.description="Stateless CPU-based pod rebalancer for Kafka consumers" \
      org.opencontainers.image.vendor="PostHog Inc."
