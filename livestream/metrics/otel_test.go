package metrics

import (
	"context"
	"testing"

	"github.com/posthog/posthog/livestream/configs"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestSetupOTelSDK(t *testing.T) {
	ctx := context.Background()

	t.Run("ConsoleEnabled_True_For_Traces_Only", func(t *testing.T) {
		otelConfig := &configs.OtelConfig{
			ConsoleEnabled: true,
		}
		shutdown, err := SetupOTelSDK(ctx, otelConfig)
		require.NoError(t, err, "SetupOTelSDK should not error with ConsoleEnabled=true")
		require.NotNil(t, shutdown, "Shutdown function should be returned")

		// TODO: Add more specific checks here to verify that traces would go to console
		// and metrics/logs would not. This might involve inspecting the global providers
		// or capturing stdout if traces are actually emitted during test.

		err = shutdown(ctx)
		assert.NoError(t, err, "Shutdown should not error")
	})

	t.Run("ConsoleEnabled_False_For_All", func(t *testing.T) {
		otelConfig := &configs.OtelConfig{
			ConsoleEnabled: false,
		}
		shutdown, err := SetupOTelSDK(ctx, otelConfig)
		require.NoError(t, err, "SetupOTelSDK should not error with ConsoleEnabled=false")
		require.NotNil(t, shutdown, "Shutdown function should be returned")

		// TODO: Add more specific checks here to verify that no OTel output goes to console.

		err = shutdown(ctx)
		assert.NoError(t, err, "Shutdown should not error")
	})
}