package main

import (
	"net"
	"os"
	"strings"
	"syscall"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// IPPROTO_MPTCP, which the syscall package does not define.
const ipProtoMPTCP = 262

func kernelSupportsMPTCP(t *testing.T) bool {
	t.Helper()

	enabled, err := os.ReadFile("/proc/sys/net/mptcp/enabled")
	if err != nil || strings.TrimSpace(string(enabled)) != "1" {
		return false
	}

	fd, err := syscall.Socket(syscall.AF_INET, syscall.SOCK_STREAM, ipProtoMPTCP)
	if err != nil {
		return false
	}
	require.NoError(t, syscall.Close(fd))

	return true
}

func listenerProtocol(t *testing.T, listener net.Listener) int {
	t.Helper()

	tcpListener, ok := listener.(*net.TCPListener)
	require.True(t, ok, "expected a *net.TCPListener, got %T", listener)

	rawConn, err := tcpListener.SyscallConn()
	require.NoError(t, err)

	var protocol int
	var sockErr error
	require.NoError(t, rawConn.Control(func(fd uintptr) {
		protocol, sockErr = syscall.GetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_PROTOCOL)
	}))
	require.NoError(t, sockErr)

	return protocol
}

// MPTCP on through GODEBUG, so this covers the per-socket opt-out, not the directive.
func TestNewListenerUsesTCPNotMPTCP(t *testing.T) {
	if !kernelSupportsMPTCP(t) {
		t.Skip("kernel does not support MPTCP, every listener is plain TCP")
	}

	t.Setenv("GODEBUG", "multipathtcp=1")
	require.True(t, new(net.ListenConfig).MultipathTCP(), "GODEBUG override did not take effect")

	listener, err := newListener(t.Context(), "127.0.0.1:0")
	require.NoError(t, err)
	t.Cleanup(func() { _ = listener.Close() })

	assert.Equal(t, syscall.IPPROTO_TCP, listenerProtocol(t, listener))
}

// Echo set a 3 minute keep-alive idle timeout; 15 seconds would drop quiet SSE streams.
func TestNewListenerKeepsThreeMinuteKeepAlive(t *testing.T) {
	listener, err := newListener(t.Context(), "127.0.0.1:0")
	require.NoError(t, err)
	t.Cleanup(func() { _ = listener.Close() })

	accepted := make(chan *net.TCPConn, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			close(accepted)
			return
		}
		accepted <- conn.(*net.TCPConn)
	}()

	client, err := net.Dial("tcp", listener.Addr().String())
	require.NoError(t, err)
	t.Cleanup(func() { _ = client.Close() })

	server := <-accepted
	require.NotNil(t, server)
	t.Cleanup(func() { _ = server.Close() })

	rawConn, err := server.SyscallConn()
	require.NoError(t, err)

	var idle int
	require.NoError(t, rawConn.Control(func(fd uintptr) {
		idle, err = syscall.GetsockoptInt(int(fd), syscall.IPPROTO_TCP, syscall.TCP_KEEPIDLE)
	}))
	require.NoError(t, err)

	assert.Equal(t, 180, idle)
}
