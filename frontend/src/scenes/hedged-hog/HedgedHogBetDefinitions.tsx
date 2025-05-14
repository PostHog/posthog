import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { hedgedHogBetDefinitionsLogic } from './hedgedHogBetDefinitionsLogic'
import { BetDefinition } from './hedgedHogBetDefinitionsLogic'

export const BetDefinitionForm = (): JSX.Element => {
    return (
        <Form logic={hedgedHogBetDefinitionsLogic} formKey="betDefinition" enableFormOnSubmit className="space-y-4">
            <Field name="title" label="Title">
                <LemonInput placeholder="E.g. Weekly pageviews for homepage" />
            </Field>

            <Field name="description" label="Description">
                <LemonTextArea placeholder="Add details about what this bet measures and how it will be evaluated" />
            </Field>

            <Field name="type" label="Bet Type">
                <LemonSelect options={[{ value: 'pageviews', label: 'Page Views' }]} />
            </Field>

            <Field
                name="bet_parameters"
                label="Bet Parameters"
                help="Enter the parameters as a JSON object, e.g. {'url': '/path', 'filters': {...}}"
            >
                {({ value, onChange }) => (
                    <LemonTextArea
                        placeholder='{"url": "/path/to/page", "filters": {"country": ["US", "CA"]}}'
                        value={typeof value === 'object' ? JSON.stringify(value, null, 2) : value}
                        onChange={(val) => {
                            try {
                                // Try to parse as JSON if it's a valid JSON string
                                const parsed = JSON.parse(val)
                                onChange(parsed)
                            } catch {
                                // If it's not valid JSON yet, just store the raw string
                                onChange(val)
                            }
                        }}
                        rows={4}
                    />
                )}
            </Field>

            <Field name="closing_date" label="Closing Date">
                {({ value, onChange }) => (
                    <LemonCalendarSelectInput
                        onChange={onChange}
                        value={value ? dayjs(value) : null}
                        granularity="hour"
                    />
                )}
            </Field>

            <Field name="probability_distribution_interval" label="Distribution Update Interval (seconds)">
                <LemonInput type="number" min={60} />
            </Field>

            <LemonButton type="primary" htmlType="submit">
                Create Bet Definition
            </LemonButton>
        </Form>
    )
}

export const BetDefinitionsContent = (): JSX.Element => {
    const logic = hedgedHogBetDefinitionsLogic()
    const { betDefinitions, betDefinitionsLoading, showNewForm } = useValues(logic)
    const { setShowNewForm } = useActions(logic)

    return (
        <div className="mt-4">
            <div className="flex justify-between items-center mb-4">
                <h3>Available Bets</h3>
                <LemonButton type="primary" onClick={() => setShowNewForm(true)} icon={<IconOpenInNew />}>
                    Create New Bet
                </LemonButton>
            </div>

            {showNewForm && (
                <LemonCard className="mb-4" hoverEffect={false}>
                    <h4 className="mb-4">Create New Bet Definition</h4>
                    <BetDefinitionForm />
                </LemonCard>
            )}

            {betDefinitionsLoading ? (
                <div className="text-center">Loading...</div>
            ) : betDefinitions.length > 0 ? (
                <div className="space-y-4">
                    {betDefinitions.map((bet: BetDefinition) => (
                        <LemonCard key={bet.id} className="p-4" hoverEffect={false}>
                            <div className="flex justify-between">
                                <div>
                                    <h4>{bet.title}</h4>
                                    <p className="text-muted">{bet.description}</p>
                                </div>
                                <div className="text-right">
                                    <div className="font-bold">{bet.status}</div>
                                    <div className="text-muted">
                                        Closes: {dayjs(bet.closing_date).format('MMM D, YYYY')}
                                    </div>
                                </div>
                            </div>
                            <LemonDivider className="my-3" />
                            <div className="text-sm">
                                <div>Type: {bet.type}</div>
                                <div>
                                    URL:{' '}
                                    {bet.bet_parameters && 'url' in bet.bet_parameters ? bet.bet_parameters.url : 'N/A'}
                                </div>
                            </div>
                        </LemonCard>
                    ))}
                </div>
            ) : (
                <LemonCard className="p-6" hoverEffect={false}>
                    <div className="text-center">
                        <h3 className="text-lg font-semibold">No Bets Available</h3>
                        <p className="text-muted mt-2">Create your first bet definition to get started.</p>
                    </div>
                </LemonCard>
            )}
        </div>
    )
}
