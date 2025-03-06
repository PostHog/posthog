.PHONY: all test lint build clean

all: build

test:
	go test ./...

lint:
	golangci-lint run ./...

build:
	@for dir in services/*; do \
		if [ -f $$dir/main.go ]; then \
			echo "Building $$dir..."; \
			(cd $$dir && go build -o ../../bin/$$(basename $$dir)); \
		fi \
	done

clean:
	rm -rf bin/
	find . -name "*.test" -delete 