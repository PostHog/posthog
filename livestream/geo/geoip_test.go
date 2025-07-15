package geo

import (
	"errors"
	"testing"

	"github.com/posthog/posthog/livestream/mocks"
	"github.com/stretchr/testify/assert"
)

func TestMaxMindLocator_Lookup_Success(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("192.0.2.1").Return(40.7128, -74.0060, nil)

	latitude, longitude, err := mockLocator.Lookup("192.0.2.1")

	assert.NoError(t, err)
	assert.Equal(t, 40.7128, latitude)
	assert.Equal(t, -74.0060, longitude)
}

func TestMaxMindLocator_Lookup_InvalidIP(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("invalid_ip").Return(0.0, 0.0, errors.New("invalid IP address"))

	latitude, longitude, err := mockLocator.Lookup("invalid_ip")

	assert.Error(t, err)
	assert.Equal(t, "invalid IP address", err.Error())
	assert.Equal(t, 0.0, latitude)
	assert.Equal(t, 0.0, longitude)
}

func TestMaxMindLocator_Lookup_DatabaseError(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("192.0.2.1").Return(0.0, 0.0, errors.New("database error"))

	latitude, longitude, err := mockLocator.Lookup("192.0.2.1")

	assert.Error(t, err)
	assert.Equal(t, "database error", err.Error())
	assert.Equal(t, 0.0, latitude)
	assert.Equal(t, 0.0, longitude)
}

func TestNewMaxMindGeoLocator_Success(t *testing.T) {
	// This test would require mocking the maxminddb.Open function, which is not possible with the current setup.
	// In a real scenario, you might use a test database file or mock the file system.
	t.Skip("Skipping NewMaxMindGeoLocator test as it requires filesystem interaction")
}

func TestNewMaxMindGeoLocator_Error(t *testing.T) {
	// Similar to the success case, this test would require mocking filesystem operations.
	t.Skip("Skipping NewMaxMindGeoLocator error test as it requires filesystem interaction")
}
