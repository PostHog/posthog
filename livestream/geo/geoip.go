package geo

import (
	"errors"
	"net"

	"github.com/oschwald/maxminddb-golang"
)

type MaxMindLocator struct {
	db *maxminddb.Reader
}

type GeoLookupResult struct {
	Latitude    float64
	Longitude   float64
	CountryCode string
}

type GeoLocator interface {
	Lookup(ipString string) (GeoLookupResult, error)
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

func (g *MaxMindLocator) Lookup(ipString string) (GeoLookupResult, error) {
	ip := net.ParseIP(ipString)
	if ip == nil {
		return GeoLookupResult{}, errors.New("invalid IP address")
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

	err := g.db.Lookup(ip, &record)
	if err != nil {
		return GeoLookupResult{}, err
	}
	return GeoLookupResult{
		Latitude:    record.Location.Latitude,
		Longitude:   record.Location.Longitude,
		CountryCode: record.Country.ISOCode,
	}, nil
}
