package steps

// StepCompleteMsg signals that a step has completed successfully
type StepCompleteMsg struct {
	Data interface{}
}

// ErrorMsg signals an error occurred
type ErrorMsg struct {
	Err error
}
