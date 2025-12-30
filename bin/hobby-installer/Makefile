.PHONY: build build-linux build-darwin clean test run deps demo

# Binary name
BINARY_NAME=posthog-hobby
DEMO_BINARY=posthog-hobby-demo
OUTPUT_DIR=..

# Go parameters
GOCMD=go
GOBUILD=$(GOCMD) build
GOCLEAN=$(GOCMD) clean
GOTEST=$(GOCMD) test
GOGET=$(GOCMD) get
GOMOD=$(GOCMD) mod

# Build flags for smaller binary
LDFLAGS=-ldflags "-s -w"

# Default target
all: build-linux

# Install dependencies
deps:
	$(GOMOD) download
	$(GOMOD) tidy

# Build for current platform (development)
build: deps
	$(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME) .

# Build for Linux (production - hobby deployments are on Ubuntu)
build-linux: deps
	GOOS=linux GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME) .

# Build for macOS (for local testing)
build-darwin: deps
	GOOS=darwin GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME)-darwin .

# Build for both platforms
build-all: build-linux build-darwin

# Run locally (macOS)
run: build-darwin
	$(OUTPUT_DIR)/$(BINARY_NAME)-darwin

# Build demo binary
demo-build: deps
	$(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(DEMO_BINARY) ./demo

# Run a demo (usage: make demo DEMO=checks)
demo: demo-build
	$(OUTPUT_DIR)/$(DEMO_BINARY) $(DEMO)

# Clean build artifacts
clean:
	$(GOCLEAN)
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)-darwin
	rm -f $(OUTPUT_DIR)/$(DEMO_BINARY)
	rm -f hobby-installer

# Run tests
test:
	$(GOTEST) -v ./...

# Format code
fmt:
	$(GOCMD) fmt ./...

# Lint code
lint:
	golangci-lint run

# Show help
help:
	@echo "PostHog Hobby Installer - Build Targets"
	@echo ""
	@echo "  make                   Build Linux binary (default)"
	@echo "  make build             Build for current platform"
	@echo "  make build-linux       Build for Linux/Ubuntu"
	@echo "  make build-darwin      Build for macOS"
	@echo "  make build-all         Build for all platforms"
	@echo "  make run               Build and run locally (macOS)"
	@echo "  make demo DEMO=checks  Run a demo (checks, etc.)"
	@echo "  make clean             Remove build artifacts"
	@echo "  make deps              Download dependencies"
	@echo "  make test              Run tests"
	@echo "  make fmt               Format code"
	@echo ""

