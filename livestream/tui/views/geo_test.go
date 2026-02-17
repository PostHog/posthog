package views

import (
	"testing"
	"time"

	"github.com/posthog/posthog/livestream/tui/sse"
	"github.com/stretchr/testify/assert"
)

func TestGeoView_AddEvent(t *testing.T) {
	v := NewGeoView()
	v.SetSize(80)

	v.AddEvent(sse.GeoEventMsg{CountryCode: "US", Count: 1, ReceivedAt: time.Now()})
	v.AddEvent(sse.GeoEventMsg{CountryCode: "GB", Count: 2, ReceivedAt: time.Now()})
	v.AddEvent(sse.GeoEventMsg{CountryCode: "US", Count: 3, ReceivedAt: time.Now()})

	// View should render without error
	output := v.View()
	assert.NotEmpty(t, output)
}

func TestGeoView_EmptyState(t *testing.T) {
	v := NewGeoView()
	v.SetSize(80)

	output := v.View()
	assert.Contains(t, output, "waiting for data")
}
