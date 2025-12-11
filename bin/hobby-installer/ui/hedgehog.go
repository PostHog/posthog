package ui

import (
	"fmt"
	"math/rand"

	"github.com/charmbracelet/lipgloss"
)

var hedgehogMoods = []string{
	"  /)_/)  \n ( o.o ) \n  > ^ <  ",
	"  /)_/)  \n ( ^.^ ) \n  > ^ <  ",
	"  /)_/)  \n ( >.< ) \n  > ^ <  ",
	"  /)_/)  \n ( o.O ) \n  > ^ <  ",
	"  /)_/)  \n ( -.- ) \n  > ^ <  ",
}

var hedgehogMessages = []string{
	"Press space to pet the hedgehog",
	"The hedgehog seems happy!",
	"You've pet the hedgehog %d times",
	"The hedgehog really likes you!",
	"Best friends! (%d pets)",
}

type Hedgehog struct {
	mood     int
	petCount int
}

func NewHedgehog() Hedgehog {
	return Hedgehog{
		mood:     0,
		petCount: 0,
	}
}

func (h *Hedgehog) Pet() {
	h.petCount++
	h.mood = rand.Intn(len(hedgehogMoods))
}

func (h Hedgehog) PetCount() int {
	return h.petCount
}

func (h Hedgehog) GetMessage() string {
	switch {
	case h.petCount == 0:
		return hedgehogMessages[0]
	case h.petCount == 1:
		return hedgehogMessages[1]
	case h.petCount < 5:
		return fmt.Sprintf(hedgehogMessages[2], h.petCount)
	case h.petCount < 10:
		return hedgehogMessages[3]
	default:
		return fmt.Sprintf(hedgehogMessages[4], h.petCount)
	}
}

func (h Hedgehog) Render() string {
	return lipgloss.NewStyle().
		Foreground(ColorPrimary).
		Render(hedgehogMoods[h.mood])
}

func (h Hedgehog) RenderWithMessage() string {
	return lipgloss.JoinVertical(
		lipgloss.Center,
		h.Render(),
		MutedStyle.Render(h.GetMessage()),
	)
}

