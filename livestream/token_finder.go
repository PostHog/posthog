package main

import "fmt"

type Location struct {
	Path  string
	Value interface{}
}

type TokenFinder struct {
	JSONChan  chan map[string]interface{}
	Locations []Location
}

func NewTokenFinder(JSONChan chan map[string]interface{}) *TokenFinder {
	return &TokenFinder{
		JSONChan:  JSONChan,
		Locations: make([]Location, 0),
	}
}

func (tf *TokenFinder) Run() {
	for {
		select {
		case newJSON := <-tf.JSONChan:
			tf.Process(newJSON, "")
		}
	}
}

func (tf *TokenFinder) Process(data map[string]interface{}, path string) {
	for key, value := range data {
		currentPath := path
		if currentPath != "" {
			currentPath += "."
		}
		currentPath += key

		// Check if this is a token key
		if key == "token" {
			tf.Locations = append(tf.Locations, Location{
				Path:  currentPath,
				Value: value,
			})
		}

		// Recursively process nested objects
		switch v := value.(type) {
		case map[string]interface{}:
			tf.Process(v, currentPath)
		case []interface{}:
			for i, item := range v {
				if obj, ok := item.(map[string]interface{}); ok {
					arrayPath := fmt.Sprintf("%s[%d]", currentPath, i)
					tf.Process(obj, arrayPath)
				}
			}
		}
	}
}
