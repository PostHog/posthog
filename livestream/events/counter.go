package events

import (
	"sync"
)

// Counter is a thread-safe reference-counted set of strings.
// Each key tracks how many times it has been added. A key is only
// removed from the set when its count reaches zero.
//
// This is useful for tracking registrations where multiple consumers
// may register interest in the same key, and the key should only be
// considered "inactive" when all consumers have unregistered.
type Counter struct {
	keys map[string]int
	mu   sync.RWMutex
}

// NewCounter creates a new empty Counter.
func NewCounter() *Counter {
	return &Counter{
		keys: make(map[string]int),
	}
}

// Add increments the count for the given key.
// Empty strings are ignored.
func (c *Counter) Add(key string) {
	if key == "" {
		return
	}
	c.mu.Lock()
	c.keys[key]++
	c.mu.Unlock()
}

// Remove decrements the count for the given key.
// If the count reaches zero, the key is removed from the set.
// Empty strings are ignored.
func (c *Counter) Remove(key string) {
	if key == "" {
		return
	}
	c.mu.Lock()
	if c.keys[key] > 1 {
		c.keys[key]--
	} else {
		delete(c.keys, key)
	}
	c.mu.Unlock()
}

// Has returns true if the key exists in the set (count > 0).
func (c *Counter) Has(key string) bool {
	c.mu.RLock()
	_, exists := c.keys[key]
	c.mu.RUnlock()
	return exists
}

// HasAny returns true if the set is non-empty.
func (c *Counter) HasAny() bool {
	c.mu.RLock()
	hasAny := len(c.keys) > 0
	c.mu.RUnlock()
	return hasAny
}
