import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { dayjs } from 'lib/dayjs'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCalendarSelectInput } from 'lib/lemon-ui/LemonCalendar'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { BillingLineGraph } from 'scenes/billing/BillingLineGraph'

import { hedgedHogBetDefinitionsLogic } from './hedgedHogBetDefinitionsLogic'
import { BetDefinition } from './hedgedHogBetDefinitionsLogic'

const BetDefinitionForm = ({ setShowNewForm }: { setShowNewForm: (show: boolean) => void }): JSX.Element => {
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

            {/* <Field
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
                                const parsed = JSON.parse(val)
                                onChange(parsed)
                            } catch {
                                onChange(val)
                            }
                        }}
                        rows={4}
                    />
                )}
            </Field> */}

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

            <div className="flex justify-between items-center pt-4">
                <LemonButton type="secondary" onClick={() => setShowNewForm(false)}>
                    Cancel
                </LemonButton>
                <LemonButton type="primary" htmlType="submit">
                    Create
                </LemonButton>
            </div>
        </Form>
    )
}

export function BettingContent(): JSX.Element {
    const logic = hedgedHogBetDefinitionsLogic()
    const { betDefinitions, betDefinitionsLoading, showNewForm } = useValues(logic)
    const { setShowNewForm } = useActions(logic)

    const mockData = {
        dates: ['Jan 8', 'Jan 19', 'Jan 31', 'Feb 11', 'Feb 28', 'Mar 11', 'Mar 31', 'Apr 11', 'Apr 30', 'May 11'],
        values: [85, 75, 80, 70, 60, 70, 55, 45, 35, 40],
    }
    const secondLineData = [15, 25, 20, 35, 40, 30, 45, 55, 65, 60]

    return (
        <div className="space-y-4">
            <div className="flex justify-between items-center mb-4">
                <div />
                <LemonButton type="primary" onClick={() => setShowNewForm(true)}>
                    Create bet definition
                </LemonButton>
            </div>

            <LemonModal isOpen={showNewForm} onClose={() => setShowNewForm(false)} title="Create Bet Definition">
                <BetDefinitionForm setShowNewForm={setShowNewForm} />
            </LemonModal>

            {betDefinitionsLoading ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    <LemonSkeleton className="h-[440px]" />
                    <LemonSkeleton className="h-[440px]" />
                    <LemonSkeleton className="h-[440px]" />
                </div>
            ) : betDefinitions.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {betDefinitions.map((bet: BetDefinition) => (
                        <Link key={bet.id} to={`/betting/${bet.id}`} className="no-underline">
                            <div className="border rounded p-6 relative border-primary h-full hover:bg-surface-primary transition-colors duration-200">
                                <div className="flex flex-col h-full">
                                    <div className="flex-grow">
                                        <h4 className="text-lg font-semibold mb-2">{bet.title}</h4>
                                        <p className="text-muted mb-4">{bet.description}</p>

                                        <div className="mb-4">
                                            <span className="text-2xl font-bold">39%</span>
                                            <span className="text-sm text-success ml-2">↑ 20%</span>
                                        </div>

                                        <div className="h-40 mb-4">
                                            <BillingLineGraph
                                                containerClassName="h-full"
                                                series={[
                                                    {
                                                        id: 1,
                                                        label: 'Yes',
                                                        data: mockData.values,
                                                        dates: mockData.dates,
                                                    },
                                                    {
                                                        id: 2,
                                                        label: 'No',
                                                        data: secondLineData,
                                                        dates: mockData.dates,
                                                    },
                                                ]}
                                                dates={mockData.dates}
                                                hiddenSeries={[]}
                                                valueFormatter={(value) => `${value}%`}
                                                interval="day"
                                                max={100}
                                                showLegend={false}
                                            />
                                        </div>
                                    </div>

                                    <div className="mt-auto">
                                        <LemonDivider className="my-3" />
                                        <div className="flex justify-between items-center">
                                            <div className="text-sm">
                                                <div>Type: {bet.type}</div>
                                                <div className="text-muted">
                                                    Closes: {dayjs(bet.closing_date).format('MMM D, YYYY')}
                                                </div>
                                            </div>
                                            <div className="text-right">
                                                <div className="font-bold">{bet.status}</div>
                                                <div className="text-muted">Volume: $5,343,183</div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </Link>
                    ))}
                </div>
            ) : (
                !showNewForm && (
                    <LemonCard className="p-6" hoverEffect={false}>
                        <div className="text-center">
                            <h3 className="text-lg font-semibold">No Bets Available</h3>
                            <p className="text-muted mt-2">Create your first bet definition to get started.</p>
                        </div>
                    </LemonCard>
                )
            )}
        </div>
    )
}
