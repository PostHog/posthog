package events

import "sync/atomic"

func makeTestSub(id uint64, token string, opts ...func(*Subscription)) Subscription {
	sub := Subscription{
		SubID:         id,
		TeamId:        1,
		Token:         token,
		EventChan:     make(chan interface{}, 100),
		ShouldClose:   &atomic.Bool{},
		DroppedEvents: &atomic.Uint64{},
	}
	for _, o := range opts {
		o(&sub)
	}
	return sub
}
