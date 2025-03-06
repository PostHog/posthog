FROM golang:1.24 AS builder
WORKDIR /code
COPY go.sum go.mod ./
RUN go mod download -x

COPY . ./
RUN go get ./...
RUN go build -v -o / .

FROM ubuntu:24.04

CMD ["/apiexample"]
