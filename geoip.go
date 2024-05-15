package main

import (
	"log"
	"net"

	"github.com/oschwald/maxminddb-golang"
)

type GeoLocator struct {
	db *maxminddb.Reader
}

func NewGeoLocator(dbPath string) (*GeoLocator, error) {
	db, err := maxminddb.Open(dbPath)
	if err != nil {
		log.Fatal(err)
	}

	return &GeoLocator{
		db: db,
	}, nil
}

func (g *GeoLocator) Lookup(ipString string) (float64, float64) {
	ip := net.ParseIP(ipString)
	if ip == nil {
		return 0, 0
	}

	var record struct {
		Location struct {
			Latitude  float64 `maxminddb:"latitude"`
			Longitude float64 `maxminddb:"longitude"`
		} `maxminddb:"location"`
	}

	err := g.db.Lookup(ip, &record)
	if err != nil {
		log.Panic(err)
	}

	return record.Location.Latitude, record.Location.Longitude
}
