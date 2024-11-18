export interface StackFrame {
    filename: string
    lineno: number
    colno: number
    function: string
    in_app?: boolean
}
