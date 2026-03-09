package tui

import "charm.land/bubbles/v2/key"

// keyMap defines all keybindings for the TUI.
type keyMap struct {
	PrevProc   key.Binding
	NextProc   key.Binding
	ScrollUp   key.Binding
	ScrollDown key.Binding
	GotoTop    key.Binding
	GotoBottom key.Binding
	SwapFocus  key.Binding
	Restart    key.Binding
	Quit       key.Binding
	Help       key.Binding
}

func defaultKeyMap() keyMap {
	return keyMap{
		PrevProc: key.NewBinding(
			key.WithKeys("up"),
			key.WithHelp("↑", "prev process"),
		),
		NextProc: key.NewBinding(
			key.WithKeys("down"),
			key.WithHelp("↓", "next process"),
		),
		ScrollUp: key.NewBinding(
			key.WithKeys("pgup"),
			key.WithHelp("pgup", "scroll up"),
		),
		ScrollDown: key.NewBinding(
			key.WithKeys("pgdn"),
			key.WithHelp("pgdn", "scroll down"),
		),
		GotoTop: key.NewBinding(
			key.WithKeys("home"),
			key.WithHelp("home", "top"),
		),
		GotoBottom: key.NewBinding(
			key.WithKeys("end"),
			key.WithHelp("end", "bottom"),
		),
		SwapFocus: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("tab", "swap focus"),
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
	return []key.Binding{k.NextProc, k.PrevProc, k.SwapFocus, k.Restart, k.Quit, k.Help}
}

// FullHelp implements help.KeyMap, shown when the user presses '?'.
func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.NextProc, k.PrevProc},
		{k.ScrollUp, k.ScrollDown},
		{k.GotoTop, k.GotoBottom},
		{k.SwapFocus},
		{k.Restart, k.Quit, k.Help},
	}
}
