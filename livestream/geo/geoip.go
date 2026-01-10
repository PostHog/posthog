package geo

import (
	"errors"
	"net/netip"

	"github.com/oschwald/maxminddb-golang/v2"
)

type MaxMindLocator struct {
	db *maxminddb.Reader
}

type GeoResult struct {
	Latitude    *float64
	Longitude   *float64
	CountryCode *string
}

type GeoLocator interface {
	Lookup(ipString string) (GeoResult, error)
}

func NewMaxMindGeoLocator(dbPath string) (*MaxMindLocator, error) {
	db, err := maxminddb.Open(dbPath)
	if err != nil {
		return nil, err
	}

	return &MaxMindLocator{
		db: db,
	}, nil
}

func (g *MaxMindLocator) Lookup(ipString string) (GeoResult, error) {
	ip, err := netip.ParseAddr(ipString)
	if err != nil {
		return GeoResult{}, errors.New("invalid IP address")
	}

	result := g.db.Lookup(ip)
	if err := result.Err(); err != nil {
		return GeoResult{}, err
	}

	if !result.Found() {
		return GeoResult{}, nil
	}

	var record struct {
		Location struct {
			Latitude  float64 `maxminddb:"latitude"`
			Longitude float64 `maxminddb:"longitude"`
		} `maxminddb:"location"`
		Country struct {
			ISOCode string `maxminddb:"iso_code"`
		} `maxminddb:"country"`
	}

	if err := result.Decode(&record); err != nil {
		return GeoResult{}, err
	}

	return GeoResult{
		Latitude:    &record.Location.Latitude,
		Longitude:   &record.Location.Longitude,
		CountryCode: &record.Country.ISOCode,
	}, nil
}
