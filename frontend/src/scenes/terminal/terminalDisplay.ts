export const DISPLAY_SCRIPT = String.raw`#!/bin/sh
case "$1" in
    on) printf '\021' > /dev/ttyS1 ;;
    off) printf '\022' > /dev/ttyS1 ;;
    *) echo 'Usage: display on|off' >&2; exit 1 ;;
esac
`

const SCANCODES: Record<string, number> = {
    Escape: 1,
    Digit1: 2,
    Digit2: 3,
    Digit3: 4,
    Digit4: 5,
    Digit5: 6,
    Digit6: 7,
    Digit7: 8,
    Digit8: 9,
    Digit9: 10,
    Digit0: 11,
    Minus: 12,
    Equal: 13,
    Backspace: 14,
    Tab: 15,
    KeyQ: 16,
    KeyW: 17,
    KeyE: 18,
    KeyR: 19,
    KeyT: 20,
    KeyY: 21,
    KeyU: 22,
    KeyI: 23,
    KeyO: 24,
    KeyP: 25,
    BracketLeft: 26,
    BracketRight: 27,
    Enter: 28,
    ControlLeft: 29,
    KeyA: 30,
    KeyS: 31,
    KeyD: 32,
    KeyF: 33,
    KeyG: 34,
    KeyH: 35,
    KeyJ: 36,
    KeyK: 37,
    KeyL: 38,
    Semicolon: 39,
    Quote: 40,
    Backquote: 41,
    ShiftLeft: 42,
    Backslash: 43,
    KeyZ: 44,
    KeyX: 45,
    KeyC: 46,
    KeyV: 47,
    KeyB: 48,
    KeyN: 49,
    KeyM: 50,
    Comma: 51,
    Period: 52,
    Slash: 53,
    ShiftRight: 54,
    AltLeft: 56,
    Space: 57,
    F1: 59,
    F2: 60,
    F3: 61,
    F4: 62,
    F5: 63,
    F6: 64,
    F7: 65,
    F8: 66,
    F9: 67,
    F10: 68,
    F11: 87,
    F12: 88,
    ControlRight: 0xe01d,
    AltRight: 0xe038,
    ArrowUp: 0xe048,
    ArrowLeft: 0xe04b,
    ArrowRight: 0xe04d,
    ArrowDown: 0xe050,
    Home: 0xe047,
    End: 0xe04f,
    PageUp: 0xe049,
    PageDown: 0xe051,
    Insert: 0xe052,
    Delete: 0xe053,
}

export class TerminalDisplayInput {
    private pressed = new Set<string>()
    private lastButtons = 0

    constructor(
        private keyboard: (codes: number[]) => void,
        private mouse: (buttons: [boolean, boolean, boolean]) => void
    ) {}

    key(code: string, down: boolean): boolean {
        const scan = SCANCODES[code]
        if (!scan) {
            return false
        }
        if (down === this.pressed.has(code)) {
            return true
        }
        down ? this.pressed.add(code) : this.pressed.delete(code)
        this.keyboard([...(scan > 255 ? [0xe0] : []), (scan & 255) | (down ? 0 : 0x80)])
        return true
    }

    buttons(buttons: number): void {
        if (buttons === this.lastButtons) {
            return
        }
        this.lastButtons = buttons
        this.mouse([!!(buttons & 1), !!(buttons & 4), !!(buttons & 2)])
    }

    release(): void {
        for (const code of this.pressed) {
            this.key(code, false)
        }
        this.buttons(0)
    }
}
