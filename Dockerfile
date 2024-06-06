FROM golang:1.22 as builder
WORKDIR /code
COPY go.sum go.mod .
RUN go mod download -x

COPY . ./
RUN go get ./...
RUN go build -v -o /livestream ./...

FROM ubuntu
COPY --from=builder /livestream /livestream
CMD ["/livestream"]
