package tui

import "charm.land/bubbles/v2/key"

type keyMap struct {
	PrevProc   key.Binding
	NextProc   key.Binding
	ScrollUp   key.Binding
	ScrollDown key.Binding
	GotoTop    key.Binding
	GotoBottom key.Binding
	SwapFocus  key.Binding
	Restart    key.Binding
	Docker     key.Binding
	CopyMode   key.Binding
	CopyEsc    key.Binding
	Quit       key.Binding
	Help       key.Binding
}

func defaultKeyMap() keyMap {
	return keyMap{
		PrevProc: key.NewBinding(
			key.WithKeys("j", "up"),
			key.WithHelp("↑:", "prev"),
		),
		NextProc: key.NewBinding(
			key.WithKeys("k", "down"),
			key.WithHelp("↓:", "next"),
		),
		ScrollUp: key.NewBinding(
			key.WithKeys("pgup"),
			key.WithHelp("pgup:", "scroll up"),
		),
		ScrollDown: key.NewBinding(
			key.WithKeys("pgdn"),
			key.WithHelp("pgdn:", "scroll down"),
		),
		GotoTop: key.NewBinding(
			key.WithKeys("home"),
			key.WithHelp("home:", "top"),
		),
		GotoBottom: key.NewBinding(
			key.WithKeys("end"),
			key.WithHelp("end:", "bottom"),
		),
		SwapFocus: key.NewBinding(
			key.WithKeys("tab"),
			key.WithHelp("tab:", "swap pane"),
		),
		Restart: key.NewBinding(
			key.WithKeys("r"),
			key.WithHelp("r:", "restart"),
		),
		Docker: key.NewBinding(
			key.WithKeys("d"),
			key.WithHelp("d:", "lazydocker"),
			key.WithDisabled(),
		),
		CopyMode: key.NewBinding(
			key.WithKeys("c"),
			key.WithHelp("c:", "copy mode"),
		),
		CopyEsc: key.NewBinding(
			key.WithKeys("esc"),
			key.WithHelp("esc:", "esc copy"),
		),
		Quit: key.NewBinding(
			key.WithKeys("q", "ctrl+c"),
			key.WithHelp("q:", "quit"),
		),
		Help: key.NewBinding(
			key.WithKeys("?"),
			key.WithHelp("?:", "help"),
		),
	}
}

func (k keyMap) ShortHelp() []key.Binding {
	return []key.Binding{k.NextProc, k.PrevProc, k.SwapFocus, k.CopyMode, k.Restart, k.Quit, k.Help}
}

func (k keyMap) FullHelp() [][]key.Binding {
	return [][]key.Binding{
		{k.NextProc, k.PrevProc},
		{k.ScrollUp, k.ScrollDown},
		{k.GotoTop, k.GotoBottom},
		{k.Restart, k.SwapFocus, k.Docker},
		{k.CopyMode, k.CopyEsc},
		{k.Quit, k.Help},
	}
}
