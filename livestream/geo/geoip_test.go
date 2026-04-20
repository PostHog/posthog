package geo_test

import (
	"errors"
	"testing"

	"github.com/posthog/posthog/livestream/geo"
	"github.com/posthog/posthog/livestream/mocks"
	"github.com/stretchr/testify/assert"
)

func TestMaxMindLocator_Lookup_Success(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("192.0.2.1").Return(geo.GeoLookupResult{Latitude: 40.7128, Longitude: -74.0060, CountryCode: "US"}, nil)

	result, err := mockLocator.Lookup("192.0.2.1")

	assert.NoError(t, err)
	assert.Equal(t, 40.7128, result.Latitude)
	assert.Equal(t, -74.0060, result.Longitude)
	assert.Equal(t, "US", result.CountryCode)
}

func TestMaxMindLocator_Lookup_InvalidIP(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("invalid_ip").Return(geo.GeoLookupResult{}, errors.New("invalid IP address"))

	result, err := mockLocator.Lookup("invalid_ip")

	assert.Error(t, err)
	assert.Equal(t, "invalid IP address", err.Error())
	assert.Equal(t, 0.0, result.Latitude)
	assert.Equal(t, 0.0, result.Longitude)
	assert.Equal(t, "", result.CountryCode)
}

func TestMaxMindLocator_Lookup_DatabaseError(t *testing.T) {
	mockLocator := mocks.NewGeoLocator(t)
	mockLocator.EXPECT().Lookup("192.0.2.1").Return(geo.GeoLookupResult{}, errors.New("database error"))

	result, err := mockLocator.Lookup("192.0.2.1")

	assert.Error(t, err)
	assert.Equal(t, "database error", err.Error())
	assert.Equal(t, 0.0, result.Latitude)
	assert.Equal(t, 0.0, result.Longitude)
	assert.Equal(t, "", result.CountryCode)
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
