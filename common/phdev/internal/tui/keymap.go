package tui

import "github.com/charmbracelet/bubbles/key"

// keyMap defines all keybindings for the TUI.
type keyMap struct {
	PrevProc     key.Binding
	NextProc     key.Binding
	ScrollUp     key.Binding
	ScrollDown   key.Binding
	HalfPageUp   key.Binding
	HalfPageDown key.Binding
	GotoTop      key.Binding
	GotoBottom   key.Binding
	Restart      key.Binding
	Quit         key.Binding
	Help         key.Binding
}

func defaultKeyMap() keyMap {
	return keyMap{
		PrevProc: key.NewBinding(
			key.WithKeys("k", "shift+tab"),
			key.WithHelp("k/shift+tab", "prev process"),
		),
		NextProc: key.NewBinding(
			key.WithKeys("j", "tab"),
			key.WithHelp("j/tab", "next process"),
		),
		ScrollUp: key.NewBinding(
			key.WithKeys("up"),
			key.WithHelp("↑", "scroll up"),
		),
		ScrollDown: key.NewBinding(
			key.WithKeys("down"),
			key.WithHelp("↓", "scroll down"),
		),
		HalfPageUp: key.NewBinding(
			key.WithKeys("ctrl+u"),
			key.WithHelp("ctrl+u", "½ page up"),
		),
		HalfPageDown: key.NewBinding(
			key.WithKeys("ctrl+d"),
			key.WithHelp("ctrl+d", "½ page dn"),
		),
		GotoTop: key.NewBinding(
			key.WithKeys("g"),
			key.WithHelp("g", "top"),
		),
		GotoBottom: key.NewBinding(
			key.WithKeys("G"),
			key.WithHelp("G", "bottom"),
		),
		Restart: key.NewBinding(
			key.WithKeys("r"),
			key.WithHelp("r", "restart"),
		),
		Quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q", "quit"),
		),
		Help: key.NewBinding(
			key.WithKeys("?"),
			key.WithHelp("?", "help"),
		),
	}
}

// ShortHelp implements help.KeyMap, shown in the collapsed footer.
func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.NextProc, k.PrevProc, k.GotoBottom, k.Restart, k.Quit, k.Help}
}

// FullHelp implements help.KeyMap, shown when the user presses '?'.
func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.NextProc, k.PrevProc},
		{k.ScrollUp, k.ScrollDown, k.HalfPageUp, k.HalfPageDown},
		{k.GotoTop, k.GotoBottom},
		{k.Restart, k.Quit, k.Help},
	}
}
