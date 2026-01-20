.PHONY: build build-linux build-darwin clean test run deps demo

# Binary name
BINARY_NAME=hobby-installer
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

# Default target builds the final binary for production
all: build-linux

# Install dependencies
deps:
	$(GOMOD) download
	$(GOMOD) tidy

# Build for current platform (development)
build: deps
	$(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME)-development .

# Build for Linux (production - hobby deployments are on Ubuntu)
build-linux: deps
	GOOS=linux GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME) .

# Build for macOS (for local testing)
build-darwin: deps
	GOOS=darwin GOARCH=amd64 $(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME)-darwin .

# Build demo binary
build-demo: deps
	$(GOBUILD) $(LDFLAGS) -o $(OUTPUT_DIR)/$(BINARY_NAME)-demo ./demo

# Build all possible binaries
build-all: build build-linux build-darwin

# Run development version
run: build
	$(OUTPUT_DIR)/$(BINARY_NAME)-development

# Run a demo (usage: make demo DEMO=checks)
demo: build-demo
	$(OUTPUT_DIR)/$(BINARY_NAME)-demo $(DEMO)

# Clean build artifacts
clean:
	$(GOCLEAN)
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)-darwin
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)-development
	rm -f $(OUTPUT_DIR)/$(BINARY_NAME)-demo
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
	@echo "  make build             Build for current platform (development binary)"
	@echo "  make build-linux       Build Linux/Ubuntu amd64 binary (production)"
	@echo "  make build-darwin      Build macOS amd64 binary (local testing)"
	@echo "  make build-demo        Build demo binary"
	@echo "  make build-all         Build binaries for all supported platforms"
	@echo "  make run               Build and run development binary locally"
	@echo "  make demo DEMO=<demo>  Build and run demo binary (e.g. DEMO=checks)"
	@echo "  make clean             Remove all build artifacts"
	@echo "  make deps              Download Go dependencies"
	@echo "  make test              Run Go tests"
	@echo "  make fmt               Format Go code"
	@echo "  make lint              Run golangci-lint"
	@echo ""

