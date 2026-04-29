package bot

import (
	"testing"
)

func TestNewClassifier(t *testing.T) {
	c := NewClassifier()
	if len(c.definitions) == 0 {
		t.Fatal("expected definitions to be loaded")
	}
}

func TestClassifyBots(t *testing.T) {
	c := NewClassifier()

	tests := []struct {
		name            string
		ua              string
		wantIsBot       bool
		wantTrafficType string
		wantCategory    string
		wantBotName     string
	}{
		{
			name:            "GPTBot",
			ua:              "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
			wantIsBot:       true,
			wantTrafficType: "AI Agent",
			wantCategory:    "ai_crawler",
			wantBotName:     "GPTBot",
		},
		{
			name:            "Googlebot",
			ua:              "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
			wantIsBot:       true,
			wantTrafficType: "Bot",
			wantCategory:    "search_crawler",
			wantBotName:     "Googlebot",
		},
		{
			name:            "curl",
			ua:              "curl/8.1.2",
			wantIsBot:       true,
			wantTrafficType: "Automation",
			wantCategory:    "http_client",
			wantBotName:     "curl",
		},
		{
			name:            "ClaudeBot",
			ua:              "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; ClaudeBot/1.0; +https://anthropic.com",
			wantIsBot:       true,
			wantTrafficType: "AI Agent",
			wantCategory:    "ai_crawler",
			wantBotName:     "Claude",
		},
		{
			name:            "SemrushBot",
			ua:              "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)",
			wantIsBot:       true,
			wantTrafficType: "Bot",
			wantCategory:    "seo_crawler",
			wantBotName:     "Semrush",
		},
		{
			name:            "Chrome regular",
			ua:              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
			wantIsBot:       false,
			wantTrafficType: "Regular",
			wantCategory:    "regular",
			wantBotName:     "",
		},
		{
			name:            "empty UA is not classified",
			ua:              "",
			wantIsBot:       false,
			wantTrafficType: "Regular",
			wantCategory:    "regular",
			wantBotName:     "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := c.Classify(tt.ua)
			if result.IsBot != tt.wantIsBot {
				t.Errorf("IsBot = %v, want %v", result.IsBot, tt.wantIsBot)
			}
			if result.TrafficType != tt.wantTrafficType {
				t.Errorf("TrafficType = %q, want %q", result.TrafficType, tt.wantTrafficType)
			}
			if result.TrafficCategory != tt.wantCategory {
				t.Errorf("TrafficCategory = %q, want %q", result.TrafficCategory, tt.wantCategory)
			}
			if result.BotName != tt.wantBotName {
				t.Errorf("BotName = %q, want %q", result.BotName, tt.wantBotName)
			}
		})
	}
}

func BenchmarkClassify(b *testing.B) {
	c := NewClassifier()
	uas := []string{
		"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
		"Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko; compatible; GPTBot/1.2; +https://openai.com/gptbot)",
		"curl/8.1.2",
	}
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		c.Classify(uas[i%len(uas)])
	}
}
