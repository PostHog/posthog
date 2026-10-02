import { useActions, useValues } from 'kea'

import { IconBrowser, IconCheck, IconCloud } from '@posthog/icons'
import { LemonButton, LemonButtonProps, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { isKernelUiEnabled } from '../../utils'
import { isMarkdownNotebookContent } from '../markdownNotebookV2'
import { notebookLogic } from '../notebookLogic'
import { notebookSettingsLogic } from '../notebookSettingsLogic'
import { BrowserKernelStatus, notebookBrowserKernelLogic } from './notebookBrowserKernelLogic'
import { NotebookKernelProvider, notebookKernelProviderLogic } from './notebookKernelProviderLogic'

const PROVIDER_LABELS: Record<NotebookKernelProvider, string> = {
    browser: 'Browser',
    sandbox: 'Cloud sandbox',
}

const BROWSER_STATUS_LABELS: Record<BrowserKernelStatus, string> = {
    stopped: 'Starts when you run a cell',
    starting: 'Starting',
    ready: 'Ready',
    busy: 'Running a cell',
    error: 'Failed to start',
}

const STATUS_DOT_CLASSES: Record<BrowserKernelStatus, string> = {
    stopped: 'bg-border-bold',
    starting: 'bg-warning',
    ready: 'bg-success',
    busy: 'bg-warning',
    error: 'bg-danger',
}

function ProviderOption({ title, description }: { title: string; description: string }): JSX.Element {
    return (
        <div className="flex flex-col py-0.5">
            <span className="font-semibold">{title}</span>
            <span className="text-xs text-secondary font-normal">{description}</span>
        </div>
    )
}

/** Picks where the notebook's Python runs, and shows the browser kernel's state at a glance. */
export function NotebookKernelSelector(props: Pick<LemonButtonProps, 'size' | 'type'>): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { content, shortId, isShared } = useValues(notebookLogic)
    const { provider } = useValues(notebookKernelProviderLogic({ shortId }))
    const { setProvider } = useActions(notebookKernelProviderLogic({ shortId }))
    const { status, isRunning } = useValues(notebookBrowserKernelLogic({ shortId }))
    const { startKernel, restartKernel, stopKernel } = useActions(notebookBrowserKernelLogic({ shortId }))
    const { showKernelInfo } = useValues(notebookSettingsLogic)
    const { setShowKernelInfo } = useActions(notebookSettingsLogic)

    if (!isKernelUiEnabled(featureFlags) || !isMarkdownNotebookContent(content) || isShared) {
        return null
    }

    const isBrowser = provider === 'browser'
    const items: LemonMenuItems = [
        {
            title: 'Run Python in',
            items: [
                {
                    label: (
                        <ProviderOption
                            title="Browser"
                            description="Runs in this tab with Pyodide. Free, and each input is capped at 50,000 rows."
                        />
                    ),
                    icon: <IconBrowser />,
                    sideIcon: isBrowser ? <IconCheck /> : undefined,
                    onClick: () => setProvider('browser'),
                    'data-attr': 'notebook-kernel-provider-browser',
                },
                {
                    label: (
                        <ProviderOption
                            title="Cloud sandbox"
                            description="Runs on PostHog compute. Handles larger data, and is charged while it runs."
                        />
                    ),
                    icon: <IconCloud />,
                    sideIcon: !isBrowser ? <IconCheck /> : undefined,
                    onClick: () => setProvider('sandbox'),
                    'data-attr': 'notebook-kernel-provider-sandbox',
                },
            ],
        },
        {
            items: [
                isBrowser && !isRunning && status !== 'starting'
                    ? {
                          label: status === 'error' ? 'Try starting again' : 'Start browser kernel',
                          onClick: () => startKernel(),
                          'data-attr': 'notebook-browser-kernel-start',
                      }
                    : null,
                isBrowser && (isRunning || status === 'starting')
                    ? {
                          label: 'Restart browser kernel',
                          tooltip: 'Clears every variable and dataframe. Run the cells again afterwards.',
                          onClick: () => restartKernel(),
                          'data-attr': 'notebook-browser-kernel-restart',
                      }
                    : null,
                isBrowser && (isRunning || status === 'starting')
                    ? {
                          label: 'Stop browser kernel',
                          onClick: () => stopKernel(),
                          'data-attr': 'notebook-browser-kernel-stop',
                      }
                    : null,
                {
                    label: showKernelInfo ? 'Hide kernel details' : 'Show kernel details',
                    onClick: () => setShowKernelInfo(!showKernelInfo),
                    'data-attr': 'notebook-kernel-details-toggle',
                },
            ],
        },
    ]

    return (
        <LemonMenu items={items} placement="bottom-start">
            <LemonButton
                {...props}
                icon={isBrowser ? <IconBrowser /> : <IconCloud />}
                tooltip={
                    isBrowser ? `Browser kernel: ${BROWSER_STATUS_LABELS[status]}` : 'Python runs in a cloud sandbox'
                }
                data-attr="notebook-kernel-selector"
            >
                <span className="flex items-center gap-1.5">
                    Python: {PROVIDER_LABELS[provider]}
                    {isBrowser ? (
                        <span
                            className={`inline-block size-2 rounded-full ${STATUS_DOT_CLASSES[status]}`}
                            aria-label={BROWSER_STATUS_LABELS[status]}
                        />
                    ) : null}
                </span>
            </LemonButton>
        </LemonMenu>
    )
}
