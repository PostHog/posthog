.PHONY: all test lint build clean

all: build

test:
	@for dir in services/*; do \
		if [ -d $$dir ]; then \
			echo "Testing $$dir..."; \
			(cd $$dir && go test ./...); \
		fi \
	done

lint:
	@for dir in services/*; do \
		if [ -d $$dir ]; then \
			echo "Linting $$dir..."; \
			(cd $$dir && $(HOME)/go/bin/golangci-lint run ./...); \
		fi \
	done

build:
	@for dir in services/*; do \
		if [ -f $$dir/main.go ]; then \
			echo "Building $$dir..."; \
			(cd $$dir && go build -o ../../bin/$$(basename $$dir)); \
		fi \
	done

run-%:
	@if [ -f services/$*/main.go ]; then \
		cd services/$* && go run .; \
	else \
		echo "Service $* not found"; \
		exit 1; \
	fi

build-%:
	@if [ -f services/$*/main.go ]; then \
		echo "Building services/$*..."; \
		cd services/$* && go build -o ../../bin/$*; \
	else \
		echo "Service $* not found"; \
		exit 1; \
	fi

test-%:
	@if [ -d services/$* ]; then \
		cd services/$* && go test ./...; \
	else \
		echo "Service $* not found"; \
		exit 1; \
	fi

clean:
	rm -rf bin/
	find . -name "*.test" -delete 