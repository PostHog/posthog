import './AuthScene.scss'

const VIEWBOX_WIDTH = 1440
const VIEWBOX_HEIGHT = 800

/**
 * Two full periods sit beyond the right edge, so the layer can travel one viewBox width and start
 * over without a visible seam.
 */
function wavePath(baseline: number, amplitude: number): string {
    const firstCrest = `Q180,${baseline - amplitude} 360,${baseline}`
    const mirroredCrests = [720, 1080, 1440, 1800, 2160, 2520, 2880].map((x) => `T${x},${baseline}`).join(' ')
    return `M0,${baseline} ${firstCrest} ${mirroredCrests} L2880,${VIEWBOX_HEIGHT} L0,${VIEWBOX_HEIGHT} Z`
}

const WAVES = [
    { key: 1, baseline: 470, amplitude: 46 },
    { key: 2, baseline: 545, amplitude: 32 },
    { key: 3, baseline: 615, amplitude: 58 },
]

export function AuthSceneWaves(): JSX.Element {
    return (
        <div className="fixed inset-0 -z-10 overflow-hidden pointer-events-none" aria-hidden="true">
            <svg
                className="w-full h-full"
                viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
                preserveAspectRatio="none"
                focusable="false"
            >
                {WAVES.map(({ key, baseline, amplitude }) => (
                    <path
                        key={key}
                        className={`AuthScene__wave AuthScene__wave--${key}`}
                        d={wavePath(baseline, amplitude)}
                    />
                ))}
            </svg>
        </div>
    )
}
