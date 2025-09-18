//go:build tools
// +build tools

// This file tracks tool dependencies for the project.
// Tools listed here will be tracked in go.mod but not included in builds.
package tools

import (
	_ "github.com/golangci/golangci-lint/cmd/golangci-lint/v2"
	_ "golang.org/x/tools/cmd/goimports"
	_ "golang.org/x/vuln/cmd/govulncheck"
)
