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

// A quill label sits beside its control, and a press on the label still toggles the control. Base UI points the
// control at the label with aria-labelledby, because `label.control` finds only the hidden input next to it.
function labelledControl(target: Element): Element | null {
    const label = target.closest('label')
    if (!label) {
        return null
    }
    const labelled = label.id
        ? Array.from(document.querySelectorAll('[aria-labelledby]')).find((element) =>
              element.getAttribute('aria-labelledby')?.split(' ').includes(label.id)
          )
        : undefined
    return labelled ?? label.control
}

function soundingComponent(target: Element): Element | null {
    return target.closest(SOUNDING_SELECTOR) ?? labelledControl(target)?.closest(SOUNDING_SELECTOR) ?? null
}

export function uiSoundForTarget(target: EventTarget | null): UiSound | null {
    if (!(target instanceof Element)) {
        return null
    }
    const component = soundingComponent(target)
    if (!component || component.matches(DISABLED_SELECTOR)) {
        return null
    }
    if (!component.matches(TOGGLE_SELECTOR)) {
        return 'click'
    }
    // The press lands before the state changes, so a control that is on now is about to turn off.
    return component.matches(CHECKED_SELECTOR) ? 'toggle-off' : 'toggle-on'
}
