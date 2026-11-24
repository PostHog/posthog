export type UiSound = 'click' | 'toggle-on' | 'toggle-off'

// Renaming a class name or quill `data-slot` value below silently stops that component's sound.
const CLICK_SELECTORS = [
    '.LemonButton',
    '.LemonTabs__tab',
    '[data-slot="button"]',
    '[data-slot="tabs-trigger"]',
    '[data-slot="toggle-group-item"]',
    '[data-slot="dropdown-menu-item"]',
    '[data-slot="context-menu-item"]',
]

const TOGGLE_SELECTORS = ['.LemonSwitch', '.LemonCheckbox', '[data-slot="switch"]', '[data-slot="checkbox"]']

const SOUNDING_SELECTOR = [...CLICK_SELECTORS, ...TOGGLE_SELECTORS].join(', ')
const TOGGLE_SELECTOR = TOGGLE_SELECTORS.join(', ')

const DISABLED_SELECTOR = [
    ':disabled',
    '[aria-disabled="true"]',
    '[data-disabled]',
    '.LemonSwitch--disabled',
    '.LemonCheckbox--disabled',
].join(', ')

const CHECKED_SELECTOR = [
    '[aria-checked="true"]',
    '[data-checked]',
    '.LemonSwitch--checked',
    '.LemonCheckbox--checked',
].join(', ')

export function uiSoundForTarget(target: EventTarget | null): UiSound | null {
    if (!(target instanceof Element)) {
        return null
    }
    const component = target.closest(SOUNDING_SELECTOR)
    if (!component || component.matches(DISABLED_SELECTOR)) {
        return null
    }
    if (!component.matches(TOGGLE_SELECTOR)) {
        return 'click'
    }
    // The press lands before the state changes, so a control that is on now is about to turn off.
    return component.matches(CHECKED_SELECTOR) ? 'toggle-off' : 'toggle-on'
}
