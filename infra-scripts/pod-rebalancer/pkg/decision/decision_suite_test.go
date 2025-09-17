package decision_test

import (
	"testing"

	. "github.com/onsi/ginkgo/v2"
	. "github.com/onsi/gomega"
)

func TestDecision(t *testing.T) {
	RegisterFailHandler(Fail)
	RunSpecs(t, "Decision Suite")
}
