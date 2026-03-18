package ui

import (
	"crypto/rand"
	"fmt"
	"math/big"

	"github.com/charmbracelet/lipgloss"
)

var hedgehogMoods = []string{
	"  \\-|-/\n / o.o \\\n \\  w  /\n  '---'",
	"  \\-|-/\n / ^.^ \\\n \\  w  /\n  '---'",
	"  \\-|-/\n / >.< \\\n \\  w  /\n  '---'",
	"  \\-|-/\n / o.O \\\n \\  o  /\n  '---'",
	"  \\-|-/\n / -.- \\\n \\  z  /\n  '---'",
}

var hedgehogParty = "  \\-★-/\n / ★.★ \\\n \\  w  /\n  '---' ✨"

var hedgehogMessages = []string{
	"Press space to pet the hedgehog",
	"The hedgehog seems happy!",
	"You've pet the hedgehog %d times",
	"The hedgehog really likes you!",
	"🎉 You unlocked: SUPER HEDGEHOG MODE! 🎉",
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
	n, _ := rand.Int(rand.Reader, big.NewInt(int64(len(hedgehogMoods))))

	h.petCount++
	h.mood = int(n.Int64())
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
	case h.petCount == 100:
		return hedgehogMessages[4]
	default:
		return fmt.Sprintf(hedgehogMessages[5], h.petCount)
	}
}

func (h Hedgehog) Render() string {
	art := hedgehogMoods[h.mood]
	if h.petCount >= 100 {
		art = hedgehogParty
	}
	return lipgloss.NewStyle().
		Foreground(ColorPrimary).
		Render(art)
}

func (h Hedgehog) RenderWithMessage() string {
	return lipgloss.JoinVertical(
		lipgloss.Center,
		h.Render(),
		MutedStyle.Render(h.GetMessage()),
	)
}
