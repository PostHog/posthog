import { render } from '@testing-library/react'

import { DialogPrimitive } from './DialogPrimitive'

// Consumers (NewDashboardModal, TextCardModal) pass their own `max-h-*`, and the popup's classes go
// through tailwind-merge. twMerge keys on the modifier, so a modifier-prefixed sizing utility here
// (`sm:max-h-*`) survives alongside a consumer's plain `max-h-*` instead of being replaced by it, and
// then wins the cascade because Tailwind emits responsive variants after base utilities. That
// silently caps every dialog that sizes itself, and no other test in the suite notices.
describe('DialogPrimitive', () => {
    it("lets a consumer's own max-height replace the default instead of stacking with it", () => {
        // Unmounts explicitly: jest.setup.ts loads via `setupFiles`, which runs before `afterEach`
        // exists, so testing-library registers no auto cleanup and the tree would outlive the test.
        const { baseElement, unmount } = render(
            <DialogPrimitive open onOpenChange={() => {}} className="max-h-[calc(100vh-4rem)]">
                <div />
            </DialogPrimitive>
        )
        const popup = baseElement.querySelector('[role="dialog"]') as HTMLElement

        expect(Array.from(popup.classList).filter((c) => c.includes('max-h'))).toEqual(['max-h-[calc(100vh-4rem)]'])

        unmount()
    })
})
