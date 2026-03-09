import type { RetentionProps } from '../types'
import { mergeTheme } from '../utils/theme'

export function Retention(props: RetentionProps): JSX.Element {
    const { data, periodLabels, showPercentages = true, showCounts = false } = props
    const theme = mergeTheme(props.theme)

    if (data.length === 0) {
        return <div className={props.className}>No retention data</div>
    }

    const style: React.CSSProperties = {
        width: typeof props.width === 'number' ? `${props.width}px` : (props.width ?? '100%'),
        height: typeof props.height === 'number' ? `${props.height}px` : (props.height ?? 'auto'),
        fontFamily: theme.fontFamily,
        fontSize: theme.fontSize,
        overflow: 'auto',
    }

    return (
        <div className={props.className} style={style} role="figure" aria-label={props.ariaLabel ?? 'Retention'}>
            <table
                style={{
                    borderCollapse: 'collapse',
                    width: '100%',
                    textAlign: 'center',
                }}
            >
                <thead>
                    <tr>
                        <th style={headerCellStyle(theme)}>Cohort</th>
                        <th style={headerCellStyle(theme)}>Size</th>
                        {periodLabels.map((label) => (
                            <th key={label} style={headerCellStyle(theme)}>
                                {label}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {data.map((cohort) => {
                        const cohortSize = cohort.values[0] ?? 0
                        return (
                            <tr key={cohort.label}>
                                <td style={{ ...cellStyle(theme), fontWeight: 600, textAlign: 'left' }}>
                                    {cohort.label}
                                </td>
                                <td style={{ ...cellStyle(theme), fontWeight: 600 }}>{cohortSize.toLocaleString()}</td>
                                {cohort.values.slice(1).map((count, i) => {
                                    const pct = cohortSize > 0 ? count / cohortSize : 0
                                    const bg = retentionCellColor(pct, theme.colors[0])
                                    return (
                                        <td
                                            key={i}
                                            style={{
                                                ...cellStyle(theme),
                                                backgroundColor: bg,
                                                color: pct > 0.5 ? '#fff' : theme.axisColor,
                                            }}
                                        >
                                            {showPercentages && `${(pct * 100).toFixed(1)}%`}
                                            {showCounts && showPercentages && <br />}
                                            {showCounts && (
                                                <span style={{ fontSize: (theme.fontSize ?? 12) - 2, opacity: 0.8 }}>
                                                    {count.toLocaleString()}
                                                </span>
                                            )}
                                        </td>
                                    )
                                })}
                            </tr>
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

function headerCellStyle(theme: ReturnType<typeof mergeTheme>): React.CSSProperties {
    return {
        padding: '8px 6px',
        color: theme.axisColor,
        fontWeight: 600,
        fontSize: theme.fontSize,
        borderBottom: `1px solid ${theme.gridColor}`,
        whiteSpace: 'nowrap',
    }
}

function cellStyle(theme: ReturnType<typeof mergeTheme>): React.CSSProperties {
    return {
        padding: '6px',
        fontSize: theme.fontSize,
        whiteSpace: 'nowrap',
    }
}

function retentionCellColor(pct: number, baseColor: string): string {
    const opacity = Math.round(pct * 200 + 10)
        .toString(16)
        .padStart(2, '0')
    return `${baseColor}${opacity}`
}
