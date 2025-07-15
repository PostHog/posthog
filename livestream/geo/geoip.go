package geo

import (
	"errors"
	"net"

	"github.com/oschwald/maxminddb-golang"
)

type MaxMindLocator struct {
	db *maxminddb.Reader
}

type GeoLocator interface {
	Lookup(ipString string) (float64, float64, error)
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

func (g *MaxMindLocator) Lookup(ipString string) (float64, float64, error) {
	ip := net.ParseIP(ipString)
	if ip == nil {
		return 0, 0, errors.New("invalid IP address")
	}

	var record struct {
		Location struct {
			Latitude  float64 `maxminddb:"latitude"`
			Longitude float64 `maxminddb:"longitude"`
		} `maxminddb:"location"`
	}

	err := g.db.Lookup(ip, &record)
	if err != nil {
		return 0, 0, err
	}
	return record.Location.Latitude, record.Location.Longitude, nil
}
