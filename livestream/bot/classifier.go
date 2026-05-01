package bot

import (
	_ "embed"
	"encoding/json"
	"log"

	ahocorasick "github.com/cloudflare/ahocorasick"
)

//go:embed definitions.json
var definitionsJSON []byte

type definition struct {
	Pattern     string `json:"pattern"`
	Name        string `json:"name"`
	Category    string `json:"category"`
	TrafficType string `json:"traffic_type"`
}

type Result struct {
	IsBot           bool
	TrafficType     string // "Regular", "Bot", "AI Agent", "Automation"
	TrafficCategory string // "ai_crawler", "search_crawler", "seo_crawler", etc.
	BotName         string // "Googlebot", "GPTBot", etc.
}

var RegularResult = Result{
	IsBot:           false,
	TrafficType:     "Regular",
	TrafficCategory: "regular",
	BotName:         "",
}

type Classifier struct {
	matcher     *ahocorasick.Matcher
	definitions []definition
}

func NewClassifier() *Classifier {
	var defs []definition
	if err := json.Unmarshal(definitionsJSON, &defs); err != nil {
		log.Fatalf("bot: failed to parse definitions.json: %v", err)
	}

	patterns := make([]string, len(defs))
	for i, d := range defs {
		patterns[i] = d.Pattern
	}

	return &Classifier{
		matcher:     ahocorasick.NewStringMatcher(patterns),
		definitions: defs,
	}
}

func (c *Classifier) Classify(userAgent string) Result {
	hits := c.matcher.MatchThreadSafe([]byte(userAgent))
	if len(hits) == 0 {
		return RegularResult
	}

	// Use first match (patterns are ordered by specificity in definitions.json)
	idx := hits[0]
	d := c.definitions[idx]
	return Result{
		IsBot:           true,
		TrafficType:     d.TrafficType,
		TrafficCategory: d.Category,
		BotName:         d.Name,
	}
}
