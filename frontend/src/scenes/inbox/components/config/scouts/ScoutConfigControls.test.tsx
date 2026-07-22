import { fireEvent, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutConfigForm } from './ScoutConfigControls'

const config: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-general',
    description: 'General scout',
    scout_origin: 'canonical',
    enabled: true,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: '0 9 * * *',
    last_run_at: null,
    created_at: '2026-07-21T12:00:00Z',
}

describe('ScoutConfigForm', () => {
    beforeEach(() => initKeaTests())

    it('saves the daily run time on blur and never clears the schedule from an empty input', () => {
        const onUpdate = jest.fn()
        const { container } = render(<ScoutConfigForm config={config} onUpdate={onUpdate} />)
        const input = container.querySelector<HTMLInputElement>('input[type="time"]')

        expect(input).not.toBeNull()

        fireEvent.change(input!, { target: { value: '14:45' } })
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.blur(input!)
        expect(onUpdate).toHaveBeenCalledWith('config-1', { run_cron_schedule: '45 14 * * *' })

        // A half-typed edit blurring empty must not silently revert the scout to its rolling
        // interval — switching schedule mode is the select's job.
        fireEvent.change(input!, { target: { value: '' } })
        fireEvent.blur(input!)
        expect(onUpdate).toHaveBeenCalledTimes(1)
    })

    it('shows an unexpressible cron as a read-only custom mode without a time picker', () => {
        const onUpdate = jest.fn()
        const { container, getByText } = render(
            <ScoutConfigForm config={{ ...config, run_cron_schedule: '0 9 * * 1-5' }} onUpdate={onUpdate} />
        )

        expect(container.querySelector('input[type="time"]')).toBeNull()
        expect(getByText('Custom (0 9 * * 1-5)')).toBeTruthy()
    })
})
