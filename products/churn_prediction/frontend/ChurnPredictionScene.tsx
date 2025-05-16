import { IconLeave, IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonLabel, LemonTable } from '@posthog/lemon-ui'
import { lemonToast } from '@posthog/lemon-ui'
import api from 'lib/api'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { IconQueryEditor } from 'lib/lemon-ui/icons'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import debounce from 'lodash.debounce'
import { useEffect, useMemo, useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { hogqlQuery } from '~/queries/query'
import { ProductKey } from '~/types'

export const scene: SceneExport = {
    component: ChurnPredictionScene,
}

const PRODUCT_NAME = 'Churn prediction'
const PRODUCT_KEY = ProductKey.CHURN_PREDICTION
const PRODUCT_DESCRIPTION = 'Predict customer churn and take action to retain them.'
const PRODUCT_THING_NAME = 'churn'

type ChurnInput = {
    id: string
    name: string
    query: string
    joinKey: string
}

export function ChurnPredictionScene(): JSX.Element {
    const [churnSignalQuery, setChurnSignalQuery] = useState<ChurnInput | undefined>(
        localStorage.getItem('churn_signal_query')
            ? JSON.parse(localStorage.getItem('churn_signal_query') || '')
            : undefined
    )
    const [customerBaseQuery, setCustomerBaseQuery] = useState<ChurnInput | undefined>(
        localStorage.getItem('customer_base_query')
            ? JSON.parse(localStorage.getItem('customer_base_query') || '')
            : undefined
    )
    const [churnInputQueries, setChurnInputQueries] = useState<ChurnInput[]>(
        localStorage.getItem('churn_input_queries') ? JSON.parse(localStorage.getItem('churn_input_queries') || '') : []
    )

    // Example records to show in the table for spot checking
    const [trainingDatasetPreview, setTrainingDatasetPreview] = useState<object[]>([])
    const [trainingDatasetQuery, setTrainingDatasetQuery] = useState<string | undefined>(undefined)
    const [churnSignalDialogOpen, setChurnSignalDialogOpen] = useState<boolean>(false)
    const [customerBaseDialogOpen, setCustomerBaseDialogOpen] = useState<boolean>(false)
    const [churnInputDialogOpen, setChurnInputDialogOpen] = useState<boolean>(false)
    const [editingChurnSignal, setEditingChurnSignal] = useState<ChurnInput | undefined>(undefined)
    const [editingCustomerBase, setEditingCustomerBase] = useState<ChurnInput | undefined>(undefined)
    const [editingChurnInput, setEditingChurnInput] = useState<ChurnInput | undefined>(undefined)

    const [trainingResults, setTrainingResults] = useState<
        | {
              metrics: {
                  accuracy: number
                  precision: number
                  recall: number
                  f1: number
                  roc_auc: number
                  classification_report: Record<string, any>
              }
              feature_importance: Record<string, number>
              top_features: Array<{ Feature: string; Importance: number }>
              class_distribution: Record<string, number>
              categorical_features: string[]
              total_features: number
          }
        | undefined
    >(undefined)
    const [trainingIsLoading, setTrainingIsLoading] = useState<boolean>(false)

    const [distinctId, setDistinctId] = useState<string>('')
    const [isCalculatingRisk, setIsCalculatingRisk] = useState<boolean>(false)
    const [churnRisk, setChurnRisk] = useState<
        | {
              prediction: boolean
              probability: number
          }
        | undefined
    >(undefined)

    useEffect(() => {
        if (churnSignalQuery) {
            localStorage.setItem('churn_signal_query', JSON.stringify(churnSignalQuery))
        }
        if (customerBaseQuery) {
            localStorage.setItem('customer_base_query', JSON.stringify(customerBaseQuery))
        }
        if (churnInputQueries.length) {
            localStorage.setItem('churn_input_queries', JSON.stringify(churnInputQueries))
        }

        if (!churnSignalQuery || !customerBaseQuery || !churnInputQueries.length) {
            return
        }

        const query = `
            WITH ${customerBaseQuery.id} as (
                ${customerBaseQuery.query}
            ),
            ${churnSignalQuery.id} as (
                ${churnSignalQuery.query}
            ),
            
            ${churnInputQueries
                .map(
                    (input) => `
            ${input.id} as (${input.query})`
                )
                .join(', ')}
                
            SELECT 
                ${customerBaseQuery.id}.distinct_id as ID,
                ${churnInputQueries
                    .map((input) => `${input.id}.value as ${input.name.replaceAll(' ', '_')}`)
                    .join(', ')},
                ${churnSignalQuery.id}.value as churned
            FROM
                ${customerBaseQuery.id}
            LEFT JOIN ${churnSignalQuery.id} ON ${customerBaseQuery.id}.${customerBaseQuery.joinKey} = ${
            churnSignalQuery.id
        }.${churnSignalQuery.joinKey}
            ${churnInputQueries
                .map(
                    (input) =>
                        `LEFT JOIN ${input.id} ON ${customerBaseQuery.id}.${customerBaseQuery.joinKey} = ${input.id}.${input.joinKey}`
                )
                .join(' ')}
        `

        async function fetchTrainingDataset(query: string): Promise<void> {
            const response = await hogqlQuery(query, undefined, 'force_blocking')
            setTrainingDatasetQuery(query)
            setTrainingDatasetPreview(response.results.slice(0, 10))
        }

        void fetchTrainingDataset(query)
    }, [churnSignalQuery, customerBaseQuery, churnInputQueries])

    const trainModel = async (): Promise<void> => {
        setTrainingIsLoading(true)

        try {
            const response = await api.create(`api/environments/1/churn_prediction/train_model/`, {
                dataset_query: trainingDatasetQuery,
            })
            setTrainingResults(response)
        } catch (error) {
            lemonToast.error('Error training model: ' + (error as Error).message)
        } finally {
            setTrainingIsLoading(false)
        }
    }

    const calculateChurnRisk = async (): Promise<void> => {
        if (!distinctId || !trainingDatasetQuery) return

        setIsCalculatingRisk(true)
        try {
            const response = await api.create(`api/environments/1/churn_prediction/predict/`, {
                dataset_query: trainingDatasetQuery,
                distinct_id: distinctId,
            })
            setChurnRisk(response)
        } catch (error) {
            lemonToast.error('Error calculating churn risk: ' + (error as Error).message)
        } finally {
            setIsCalculatingRisk(false)
        }
    }

    const hasChurnSignal = churnSignalQuery !== undefined
    const hasCustomerBase = customerBaseQuery !== undefined

    const queryDialog = (churnSignalDialogOpen || customerBaseDialogOpen || churnInputDialogOpen) && (
        <QueryDialog
            input={
                churnSignalDialogOpen
                    ? editingChurnSignal
                    : customerBaseDialogOpen
                    ? editingCustomerBase
                    : editingChurnInput
            }
            type={churnSignalDialogOpen ? 'churn_signal' : customerBaseDialogOpen ? 'customer_base' : 'churn_input'}
            onSubmit={(input) => {
                if (churnSignalDialogOpen) {
                    input && setChurnSignalQuery(input)
                    setChurnSignalDialogOpen(false)
                    setEditingChurnSignal(undefined)
                } else if (customerBaseDialogOpen) {
                    input && setCustomerBaseQuery(input)
                    setCustomerBaseDialogOpen(false)
                    setEditingCustomerBase(undefined)
                } else if (editingChurnInput) {
                    input &&
                        setChurnInputQueries(churnInputQueries.map((i) => (i.id === editingChurnInput.id ? input : i)))
                    setChurnInputDialogOpen(false)
                    setEditingChurnInput(undefined)
                } else {
                    input && setChurnInputQueries([...churnInputQueries, input])
                    setChurnInputDialogOpen(false)
                }
            }}
        />
    )

    if (!hasChurnSignal && !hasCustomerBase && !churnInputQueries.length) {
        return (
            <>
                {queryDialog}
                <ProductIntroduction
                    isEmpty
                    productName={PRODUCT_NAME}
                    productKey={PRODUCT_KEY}
                    thingName={PRODUCT_THING_NAME}
                    description={PRODUCT_DESCRIPTION}
                    titleOverride="Set up churn analysis"
                    actionElementOverride={
                        <div className="flex flex-col gap-2">
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                onClick={() => {
                                    setCustomerBaseDialogOpen(true)
                                }}
                                data-attr="create-customer-base"
                            >
                                Set up customer base
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                sideIcon={<IconLeave />}
                                onClick={() => {
                                    setChurnSignalDialogOpen(true)
                                }}
                                data-attr="create-churn-indicator"
                            >
                                Set up churn signal
                            </LemonButton>
                        </div>
                    }
                />
            </>
        )
    }

    return (
        <div className="flex flex-col gap-4 items-start">
            <div className="flex flex-col gap-2 w-full mb-8">
                <div className="flex justify-between items-center">
                    <LemonLabel>Customer base</LemonLabel>
                    {!hasCustomerBase && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                setCustomerBaseDialogOpen(true)
                            }}
                            icon={<IconPlus />}
                        >
                            Add customer base
                        </LemonButton>
                    )}
                </div>

                {customerBaseQuery ? (
                    <div className="border rounded p-4 w-full">
                        <div className="flex justify-between items-center">
                            <div className="flex flex-col gap-1">
                                <div className="font-semibold">{customerBaseQuery.name}</div>
                                <div className="text-muted">Join key: {customerBaseQuery.joinKey}</div>
                            </div>
                            <div className="flex">
                                <LemonButton
                                    icon={<IconQueryEditor />}
                                    onClick={() => {
                                        setEditingCustomerBase(customerBaseQuery)
                                        setCustomerBaseDialogOpen(true)
                                    }}
                                    data-attr="edit-customer-base"
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    icon={<IconTrash />}
                                    onClick={() => {
                                        setCustomerBaseQuery(undefined)
                                    }}
                                    data-attr="delete-customer-base"
                                >
                                    Remove
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="text-muted">No customer base set</div>
                )}
            </div>

            <div className="flex flex-col gap-2 w-full mb-8">
                <div className="flex justify-between items-center">
                    <LemonLabel>Churn signal</LemonLabel>
                    {!hasChurnSignal && (
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                setChurnSignalDialogOpen(true)
                            }}
                            icon={<IconPlus />}
                        >
                            Add churn signal
                        </LemonButton>
                    )}
                </div>

                {churnSignalQuery ? (
                    <div className="border rounded p-4 w-full">
                        <div className="flex justify-between items-center">
                            <div className="flex flex-col gap-1">
                                <div className="font-semibold">{churnSignalQuery.name}</div>
                                <div className="text-muted">Join key: {churnSignalQuery.joinKey}</div>
                            </div>
                            <div className="flex">
                                <LemonButton
                                    icon={<IconQueryEditor />}
                                    onClick={() => {
                                        setEditingChurnSignal(churnSignalQuery)
                                        setChurnSignalDialogOpen(true)
                                    }}
                                    data-attr="edit-churn-signal"
                                >
                                    Edit
                                </LemonButton>
                                <LemonButton
                                    icon={<IconTrash />}
                                    onClick={() => {
                                        setChurnSignalQuery(undefined)
                                    }}
                                    data-attr="edit-churn-signal"
                                >
                                    Remove
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="text-muted">No churn signal set</div>
                )}
            </div>

            <div className="flex justify-between w-full">
                <LemonLabel>Churn model inputs</LemonLabel>
                <LemonButton
                    type="primary"
                    onClick={() => {
                        setChurnInputDialogOpen(true)
                    }}
                    icon={<IconPlus />}
                >
                    Add churn input
                </LemonButton>
            </div>

            {churnInputQueries.map((input) => (
                <div key={input.id} className="border rounded p-4 w-full">
                    <div className="flex justify-between items-center">
                        <div className="flex flex-col gap-1">
                            <div className="font-semibold">{input.name}</div>
                            <div className="text-muted">Join key: {input.joinKey}</div>
                        </div>
                        <div className="flex">
                            <LemonButton
                                icon={<IconQueryEditor />}
                                onClick={() => {
                                    setEditingChurnInput(input)
                                    setChurnInputDialogOpen(true)
                                }}
                                data-attr="edit-churn-signal"
                            >
                                Edit
                            </LemonButton>
                            <LemonButton
                                icon={<IconTrash />}
                                onClick={() => {
                                    setChurnInputQueries(churnInputQueries.filter((i) => i.id !== input.id))
                                }}
                                data-attr="delete-churn-input"
                            >
                                Remove
                            </LemonButton>
                        </div>
                    </div>
                </div>
            ))}

            <LemonLabel className="mt-8">Churn model training data preview</LemonLabel>
            {churnInputQueries.length > 0 ? (
                <LemonTable<Record<string, any>>
                    columns={[
                        {
                            title: 'ID',
                            dataIndex: '0',
                            key: '0',
                        },
                        ...churnInputQueries.map((input, idx) => ({
                            title: input.name,
                            dataIndex: `${idx + 1}`,
                            key: `${idx + 1}`,
                        })),
                        {
                            title: 'Churn',
                            dataIndex: `${churnInputQueries.length + 1}`,
                            key: `${churnInputQueries.length + 1}`,
                        },
                    ]}
                    dataSource={trainingDatasetPreview}
                />
            ) : (
                <div className="text-muted">
                    Configure a churn signal, customer base and inputs above to see model data
                </div>
            )}

            <LemonButton
                type="primary"
                loading={trainingIsLoading}
                onClick={() => void trainModel()}
                disabledReason={
                    !hasChurnSignal || !hasCustomerBase || churnInputQueries.length === 0
                        ? 'Configure a churn signal, customer base and inputs above to train a churn model'
                        : undefined
                }
            >
                {trainingResults ? 'Re-train' : 'Train'} churn model
            </LemonButton>

            {trainingResults && (
                <div className="flex flex-col gap-4 w-full">
                    <LemonLabel>Training results</LemonLabel>

                    {/* Metrics */}
                    <div className="border rounded p-4">
                        <div className="font-semibold mb-2">Model Performance</div>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <div className="text-muted">Accuracy</div>
                                <div>{(trainingResults.metrics.accuracy * 100).toFixed(1)}%</div>
                            </div>
                            <div>
                                <div className="text-muted">Precision</div>
                                <div>{(trainingResults.metrics.precision * 100).toFixed(1)}%</div>
                            </div>
                            <div>
                                <div className="text-muted">Recall</div>
                                <div>{(trainingResults.metrics.recall * 100).toFixed(1)}%</div>
                            </div>
                            <div>
                                <div className="text-muted">F1 Score</div>
                                <div>{(trainingResults.metrics.f1 * 100).toFixed(1)}%</div>
                            </div>
                            <div>
                                <div className="text-muted">ROC AUC</div>
                                <div>{(trainingResults.metrics.roc_auc * 100).toFixed(1)}%</div>
                            </div>
                        </div>
                    </div>

                    {/* Feature Importance */}
                    <div className="border rounded p-4">
                        <div className="font-semibold mb-2">Feature Importance</div>
                        <LemonTable
                            dataSource={trainingResults.top_features.map((feature) => ({
                                ...feature,
                                Feature: churnInputQueries[parseInt(feature.Feature)]?.name || feature.Feature,
                            }))}
                            columns={[
                                {
                                    title: 'Feature',
                                    dataIndex: 'Feature',
                                    key: 'Feature',
                                },
                                {
                                    title: 'Importance',
                                    dataIndex: 'Importance',
                                    key: 'Importance',
                                    render: (value: string | number | undefined) =>
                                        typeof value === 'number' ? `${value.toFixed(2)}%` : '-',
                                },
                            ]}
                        />
                    </div>

                    {/* Churn Risk Calculator */}
                    <div className="border rounded p-4">
                        <div className="font-semibold mb-2">Churn Risk Calculator</div>
                        <div className="flex flex-col gap-4">
                            <div className="flex gap-2">
                                <LemonInput
                                    placeholder="Enter distinct_id"
                                    value={distinctId}
                                    onChange={setDistinctId}
                                    className="flex-1"
                                />
                                <LemonButton
                                    type="primary"
                                    onClick={() => void calculateChurnRisk()}
                                    loading={isCalculatingRisk}
                                    disabled={!distinctId || !trainingDatasetQuery}
                                >
                                    Calculate risk
                                </LemonButton>
                            </div>
                            {churnRisk && (
                                <div className="flex flex-col gap-2">
                                    <div className="flex items-center gap-2">
                                        <div className="text-muted">Churn Risk:</div>
                                        <div
                                            className={`font-semibold ${
                                                churnRisk.probability > 0.7
                                                    ? 'text-red'
                                                    : churnRisk.probability > 0.3
                                                    ? 'text-yellow'
                                                    : 'text-green'
                                            }`}
                                        >
                                            {(churnRisk.probability * 100).toFixed(1)}%
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        <div className="text-muted">Prediction:</div>
                                        <div
                                            className={`font-semibold ${
                                                churnRisk.prediction ? 'text-red' : 'text-green'
                                            }`}
                                        >
                                            {churnRisk.prediction ? 'Likely to churn' : 'Not likely to churn'}
                                        </div>
                                    </div>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {queryDialog}
        </div>
    )
}

function createRandomString(length: number): string {
    const chars = 'abcdefghijklmnopqrstuvwxyz'
    let result = ''
    for (let i = 0; i < length; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    return result
}

function QueryDialog({
    input,
    onSubmit,
    type,
}: {
    input?: ChurnInput
    onSubmit: (input?: ChurnInput) => void
    type: 'churn_signal' | 'churn_input' | 'customer_base'
}): JSX.Element {
    const [id] = useState<string>(input?.id || createRandomString(10))
    const [name, setName] = useState<string>(input?.name || '')
    const [joinKey, setJoinKey] = useState<string>(input?.joinKey || '')
    const [hogQLQuery, setHogQLQuery] = useState<string>(input?.query || '')

    return (
        <LemonDialog
            title={
                type === 'churn_signal'
                    ? 'Add churn signal'
                    : type === 'customer_base'
                    ? 'Add customer base'
                    : 'Add churn input'
            }
            width={750}
            description={
                type === 'churn_signal'
                    ? 'A churn signal is a query that returns a single boolean value for each customer. This value should represent whether or not the customer is churning.'
                    : type === 'customer_base'
                    ? 'A customer base is a query that returns a list of customers to analyze. Filter out users that should not be analyzed. This defines the population of customers to predict churn for.'
                    : 'A churn input is a query that returns a single value for each customer. This value will be used to predict churn.'
            }
            content={
                <div className="flex flex-col gap-4">
                    <div className="flex flex-col">
                        <LemonLabel htmlFor="name">Name</LemonLabel>
                        <LemonInput value={name} onChange={(value) => setName(value)} />
                    </div>
                    <div className="flex flex-col gap-1">
                        <LemonLabel htmlFor="hogQLQuery">Query</LemonLabel>
                        <CodeEditor
                            value={hogQLQuery}
                            onChange={(value) => setHogQLQuery(value ?? '')}
                            language="sql"
                            height="200px"
                            className="rounded border"
                            options={{
                                minimap: { enabled: false },
                                wordWrap: 'on',
                                scrollBeyondLastLine: false,
                                automaticLayout: true,
                                lineNumbers: 'off',
                                fixedOverflowWidgets: true,
                                suggest: {
                                    showInlineDetails: true,
                                },
                                quickSuggestionsDelay: 300,
                            }}
                        />
                        <span className="text-sm text-muted">
                            {type === 'churn_signal'
                                ? 'Write a Data warehouse query to return a boolean value for each customer representing whether the customer has churned. Make sure to return the distinct ID or group ID in the query.'
                                : type === 'customer_base'
                                ? 'Write a Data warehouse query to return a list of customers to analyze. Make sure to return the distinct ID or group ID in the query.'
                                : 'Write a Data warehouse query to return a single value for each customer. Make sure to return the distinct ID or group ID in the query.'}
                        </span>
                    </div>
                    <div className="flex flex-col">
                        <LemonLabel
                            htmlFor="join_key"
                            info="The key to join the churn signal with the churn input. Typically, this would be a customer unique identifier like email or id"
                        >
                            Join key
                        </LemonLabel>
                        <LemonInput value={joinKey} onChange={(value) => setJoinKey(value)} />
                    </div>
                    <QueryResultsTable query={hogQLQuery} />
                </div>
            }
            primaryButton={{
                type: 'primary',
                onClick: () => onSubmit({ id, name, query: hogQLQuery, joinKey }),
                children: 'Save',
            }}
            onAfterClose={() => onSubmit()}
        />
    )
}

function QueryResultsTable({ query }: { query: string }): JSX.Element | null {
    const [results, setResults] = useState<any[]>([])
    const [columns, setColumns] = useState<any[]>([])
    const [loading, setLoading] = useState(false)

    const debouncedQuery = useMemo(
        () =>
            debounce(async (query: string) => {
                if (!query) {
                    setResults([])
                    setColumns([])
                    return
                }

                setLoading(true)
                const response = await hogqlQuery(query, undefined, 'force_blocking')

                if (response.metadata?.errors && response.metadata.errors.length > 0) {
                    lemonToast.error(
                        'Query error: ' + response.metadata.errors.map((error) => error.message).join(', ')
                    )
                    setResults([])
                    setColumns([])
                } else if (response.results && response.results.length > 0) {
                    setResults(response.results.slice(0, 10))
                    setColumns(
                        (response.columns || []).map((column, idx) => ({
                            title: column,
                            dataIndex: idx,
                            key: idx,
                        }))
                    )
                } else {
                    setResults([])
                    setColumns([])
                }

                setLoading(false)
            }, 1000),
        []
    )

    useEffect(() => {
        debouncedQuery(query)
        return () => {
            debouncedQuery.cancel()
        }
    }, [query, debouncedQuery])

    if (!query) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonLabel>Preview results</LemonLabel>
            {results.length > 0 ? (
                <LemonTable dataSource={results} columns={columns} loading={loading} emptyState="No results found" />
            ) : (
                <div className="text-muted">No results found</div>
            )}
        </div>
    )
}
