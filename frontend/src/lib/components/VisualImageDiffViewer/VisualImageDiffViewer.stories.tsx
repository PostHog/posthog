import { Meta, StoryObj } from '@storybook/react'

import { VisualImageDiffViewer } from './VisualImageDiffViewer'

type Story = StoryObj<typeof VisualImageDiffViewer>

const meta: Meta<typeof VisualImageDiffViewer> = {
    title: 'Lemon UI/Visual image diff viewer',
    component: VisualImageDiffViewer,
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            allowImagesWithoutWidth: true,
        },
    },
}

export default meta

function toSvgDataUri(svg: string): string {
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`
}

const baselineSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="860" viewBox="0 0 1400 860">
  <defs>
    <linearGradient id="bgA" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f3f6fb"/>
      <stop offset="1" stop-color="#e8edf5"/>
    </linearGradient>
  </defs>
  <rect width="1400" height="860" fill="url(#bgA)"/>
  <rect x="70" y="80" width="1260" height="700" rx="18" fill="#ffffff" stroke="#d8dee8"/>
  <rect x="70" y="80" width="1260" height="70" rx="18" fill="#f5f8fc"/>
  <rect x="100" y="106" width="180" height="20" rx="10" fill="#dbe4f1"/>
  <rect x="310" y="106" width="128" height="20" rx="10" fill="#ebeff5"/>
  <rect x="470" y="106" width="128" height="20" rx="10" fill="#ebeff5"/>
  <rect x="110" y="190" width="1180" height="560" rx="12" fill="#f7f8fb" stroke="#e1e6ef"/>
  <rect x="140" y="220" width="520" height="180" rx="8" fill="#f0f4fa"/>
  <rect x="140" y="430" width="520" height="290" rx="8" fill="#eef3fa"/>
  <rect x="700" y="220" width="560" height="500" rx="8" fill="#ecf1f8"/>
  <circle cx="290" cy="555" r="70" fill="#dbe4f1"/>
  <circle cx="430" cy="555" r="54" fill="#d0deef"/>
  <rect x="785" y="300" width="390" height="24" rx="8" fill="#d4deed"/>
  <rect x="785" y="340" width="330" height="18" rx="8" fill="#dee6f2"/>
  <rect x="785" y="380" width="250" height="18" rx="8" fill="#dee6f2"/>
  <text x="120" y="730" fill="#75839a" font-size="28" font-family="Arial">Baseline screenshot</text>
</svg>
`

const currentSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="860" viewBox="0 0 1400 860">
  <defs>
    <linearGradient id="bgB" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f2f9f8"/>
      <stop offset="1" stop-color="#e5f2f1"/>
    </linearGradient>
  </defs>
  <rect width="1400" height="860" fill="url(#bgB)"/>
  <rect x="70" y="80" width="1260" height="700" rx="18" fill="#ffffff" stroke="#cfe2de"/>
  <rect x="70" y="80" width="1260" height="70" rx="18" fill="#edf7f4"/>
  <rect x="100" y="106" width="180" height="20" rx="10" fill="#c9ebe3"/>
  <rect x="310" y="106" width="128" height="20" rx="10" fill="#d8efe9"/>
  <rect x="470" y="106" width="128" height="20" rx="10" fill="#d8efe9"/>
  <rect x="630" y="106" width="138" height="20" rx="10" fill="#bfe5da"/>
  <rect x="110" y="190" width="1180" height="560" rx="12" fill="#f6fbfa" stroke="#d5ebe6"/>
  <rect x="140" y="220" width="520" height="180" rx="8" fill="#e7f4f1"/>
  <rect x="140" y="430" width="520" height="290" rx="8" fill="#e5f2ef"/>
  <rect x="700" y="220" width="560" height="500" rx="8" fill="#e6f4f1"/>
  <circle cx="290" cy="555" r="70" fill="#a7dfcf"/>
  <circle cx="430" cy="555" r="54" fill="#98d8c6"/>
  <rect x="785" y="300" width="390" height="24" rx="8" fill="#a7d8ca"/>
  <rect x="785" y="340" width="330" height="18" rx="8" fill="#b8e0d5"/>
  <rect x="785" y="380" width="250" height="18" rx="8" fill="#b8e0d5"/>
  <rect x="785" y="430" width="420" height="220" rx="10" fill="#d6efe9" stroke="#b7ded3"/>
  <text x="120" y="730" fill="#5f8f85" font-size="28" font-family="Arial">Current screenshot</text>
</svg>
`

const diffSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="860" viewBox="0 0 1400 860">
  <rect width="1400" height="860" fill="transparent"/>
  <rect x="780" y="420" width="430" height="240" rx="10" fill="#ff4d9a" fill-opacity="0.5"/>
  <rect x="616" y="100" width="166" height="26" rx="8" fill="#ff4d9a" fill-opacity="0.45"/>
  <circle cx="288" cy="552" r="84" fill="#4d7cff" fill-opacity="0.3"/>
  <rect x="130" y="209" width="545" height="210" rx="12" fill="#4d7cff" fill-opacity="0.2"/>
</svg>
`

const newSnapshotSvg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1400" height="860" viewBox="0 0 1400 860">
  <defs>
    <linearGradient id="bgC" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#f9f7f0"/>
      <stop offset="1" stop-color="#f3efe2"/>
    </linearGradient>
  </defs>
  <rect width="1400" height="860" fill="url(#bgC)"/>
  <rect x="90" y="90" width="1220" height="680" rx="20" fill="#fffdfa" stroke="#e7dcc1"/>
  <rect x="140" y="150" width="1120" height="70" rx="14" fill="#faf3e1"/>
  <rect x="170" y="175" width="210" height="22" rx="11" fill="#ecd9aa"/>
  <rect x="140" y="260" width="530" height="460" rx="14" fill="#f9f0da"/>
  <rect x="700" y="260" width="560" height="460" rx="14" fill="#f7ecd3"/>
  <rect x="760" y="320" width="420" height="28" rx="10" fill="#e6d1a0"/>
  <rect x="760" y="370" width="340" height="20" rx="10" fill="#edddb8"/>
  <rect x="760" y="412" width="280" height="20" rx="10" fill="#edddb8"/>
  <text x="150" y="742" fill="#8e7b53" font-size="30" font-family="Arial">New snapshot</text>
</svg>
`

const baselineImage = toSvgDataUri(baselineSvg)
const currentImage = toSvgDataUri(currentSvg)
const diffImage = toSvgDataUri(diffSvg)
const newSnapshotImage = toSvgDataUri(newSnapshotSvg)

export const ChangedSnapshot: Story = {
    args: {
        baselineUrl: baselineImage,
        currentUrl: currentImage,
        diffUrl: diffImage,
        diffPercentage: 7.46,
        result: 'changed',
    },
    render: (args) => (
        <div className="p-6 bg-bg-light min-h-screen">
            <div className="mx-auto max-w-[1240px]">
                <VisualImageDiffViewer {...args} />
            </div>
        </div>
    ),
}

export const NewSnapshot: Story = {
    args: {
        baselineUrl: null,
        currentUrl: newSnapshotImage,
        diffUrl: null,
        diffPercentage: null,
        result: 'new',
    },
    render: (args) => (
        <div className="p-6 bg-bg-light min-h-screen">
            <div className="mx-auto max-w-[1240px]">
                <VisualImageDiffViewer {...args} />
            </div>
        </div>
    ),
}
