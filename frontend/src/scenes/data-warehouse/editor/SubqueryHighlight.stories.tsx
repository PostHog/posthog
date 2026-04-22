import type { Meta, StoryObj } from '@storybook/react'

import './EditorScene.scss'

// Pure-CSS visual documentation of the decoration classes applied by the SQL
// editor when the cursor sits inside a subquery/CTE. The real decorations are
// attached through Monaco's `deltaDecorations` in `sqlEditorLogic`, but
// mounting the full editor for a visual snapshot is fragile and expensive —
// so this story just renders the class names against representative SQL so a
// reviewer can eyeball the highlight colors.
function SubqueryHighlightDemo(): JSX.Element {
    return (
        <div className="whitespace-pre p-4 font-mono text-sm leading-6 bg-surface-primary">
            <div className="mb-2 font-sans text-xs text-muted">Valid standalone (blue)</div>
            <div>{'SELECT id FROM ('}</div>
            <div>
                <span className="active-subquery-highlight">{'    SELECT id FROM events WHERE team_id = 1'}</span>
            </div>
            <div>{')'}</div>

            <div className="mt-6 mb-2 font-sans text-xs text-muted">
                Would fail standalone (amber) — previously a yellow wavy underline
            </div>
            <div>{'WITH recent_events AS (SELECT id FROM events)'}</div>
            <div>{'SELECT id FROM ('}</div>
            <div>
                <span className="active-subquery-highlight-invalid">{'    SELECT id FROM recent_events'}</span>
            </div>
            <div>{')'}</div>
        </div>
    )
}

const meta: Meta<typeof SubqueryHighlightDemo> = {
    title: 'Scenes-App/Data Warehouse/Editor/Subquery highlight',
    component: SubqueryHighlightDemo,
    parameters: {
        layout: 'padded',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
}
export default meta

type Story = StoryObj<typeof SubqueryHighlightDemo>

export const Default: Story = {}
