import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

const svgSource = `data:image/svg+xml,${encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="#e87722"/><path d="M7 12h10M12 7v10" stroke="white" stroke-width="2"/></svg>'
)}`
const pngSource =
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAYAAADgdz34AAAAJUlEQVR4nGNgGAWDDig0LPhPCR61YNSCUQtGLRi1YHhYMAroDgC3sz8f5SN7GwAAAABJRU5ErkJggg=='

export const IMAGE_QUERY = `SELECT
    <img src='${svgSource}' alt='Custom SVG' width={128} height={128} /> AS image,
    'SVG logo' AS name,
    12 AS calls,
    withIcon(toBool(1), 'Claude') AS status
UNION ALL SELECT
    <img src='${pngSource}' alt='Custom PNG' width={24} height={24} />,
    'PNG logo',
    7,
    withIcon(toBool(0), 'Claude')`

export const IMAGE_RESULTS: HogQLQueryResponse = {
    columns: ['image', 'name', 'calls', 'status'],
    types: [
        ['image', 'Tuple(String, String, String, String, String, String, String, UInt8, String, UInt8)'],
        ['name', 'String'],
        ['calls', 'UInt8'],
        ['status', 'Tuple(String, String, String, Nullable(Bool), String, String)'],
    ],
    results: [
        [
            ['__hx_tag', 'img', 'src', svgSource, 'alt', 'Custom SVG', 'width', 128, 'height', 128],
            'SVG logo',
            12,
            ['__hx_tag', 'BrandMarkLabel', 'label', true, 'mark', 'Claude'],
        ],
        [
            ['__hx_tag', 'img', 'src', pngSource, 'alt', 'Custom PNG', 'width', 24, 'height', 24],
            'PNG logo',
            7,
            ['__hx_tag', 'BrandMarkLabel', 'label', false, 'mark', 'Claude'],
        ],
    ],
    hasMore: false,
}
