import { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { WizardHandoffDialog } from './WizardHandoffDialog'
import { wizardSyncUiLogic } from './wizardSyncUiLogic'

const SAMPLE_REPORT = [
    '# PostHog setup report',
    '',
    'Installed `posthog-js` and wired up event capture for a Next.js app.',
    '',
    '## What changed',
    '- Added `instrumentation-client.ts` with the PostHog init',
    '- Wrapped the app in `PostHogProvider` in `app/providers.tsx`',
    '- Added `NEXT_PUBLIC_POSTHOG_KEY` to `.env.local`',
    '',
    '## Events instrumented',
    '| Event | Where |',
    '| --- | --- |',
    '| `signed_up` | `app/signup/page.tsx` |',
    '| `checkout_started` | `app/checkout/page.tsx` |',
    '',
    '## Verify before merging',
    '- [ ] Events arrive on the Activity page',
    '- [ ] The API key lives in `.env.local`, not in source',
    '- [ ] `pnpm build` passes',
].join('\n')

// The dialog reads from wizardSyncUiLogic, so the story opens a doc through the same action the
// announce path and the "View setup report" buttons use.
function OpenedHandoffDialog(): JSX.Element {
    useMountedLogic(wizardSyncUiLogic)
    const { openHandoffDoc } = useActions(wizardSyncUiLogic)
    useEffect(() => {
        openHandoffDoc({ key: 'story-run', text: SAMPLE_REPORT })
    }, [openHandoffDoc])
    return <WizardHandoffDialog />
}

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Shared/Wizard Handoff Dialog',
    component: WizardHandoffDialog,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj<typeof WizardHandoffDialog>

export const Opened: Story = {
    render: () => <OpenedHandoffDialog />,
}
