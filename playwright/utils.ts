import { Page } from '@playwright/test'

export function randomString(prefix = ''): string {
    const id = Math.floor(Math.random() * 1e6)
    return `${prefix}-${id}`
}

export async function getLemonSwitchValue(page: Page, label: string): Promise<boolean | null> {
    const button = page.getByLabel(label)
    const parent = button.locator('..')
    const classNames = await parent.getAttribute('class')
    return classNames?.includes('LemonSwitch--checked') || null
}

export async function setLemonSwitchValue(page: Page, label: string, value: boolean): Promise<void> {
    const button = page.getByLabel(label)
    const currentValue = await getLemonSwitchValue(page, label)

    if (value !== currentValue) {
        await button.click()
    }
}
