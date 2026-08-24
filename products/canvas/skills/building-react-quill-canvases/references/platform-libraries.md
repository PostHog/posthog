# Platform libraries

The canvas builder pins ten optional libraries. Choose the smallest one that matches the job and
keep the dependency map returned by `canvas-source-retrieve` unchanged.

| Library                   | Use it for                  | Main capabilities                                                                            |
| ------------------------- | --------------------------- | -------------------------------------------------------------------------------------------- |
| `d3`                      | Bespoke data visualization  | Scales, shapes, layouts, geographic projections, interpolation, and SVG helpers              |
| `three`                   | 3D and WebGL scenes         | Cameras, geometry, materials, lighting, animation, and raycasting                            |
| `framer-motion`           | Coordinated React animation | Enter and exit transitions, layout animation, gestures, springs, and reduced-motion handling |
| `zod`                     | Runtime data validation     | Schemas, parsing, coercion, transformations, unions, and typed validation errors             |
| `@tanstack/react-table`   | Complex data tables         | Sorting, filtering, grouping, pagination, selection, and column state                        |
| `@tanstack/react-virtual` | Large tables and lists      | Windowed rows and columns, dynamic measurements, scrolling, and overscan                     |
| `react-hook-form`         | Multi-field forms           | Field registration, validation, dirty state, controlled inputs, and submission state         |
| `lodash-es`               | Data transformation         | Grouping, ordering, deduplication, aggregation, object selection, and collection helpers     |
| `react-markdown`          | Safe Markdown presentation  | Markdown parsing into React elements without `dangerouslySetInnerHTML`                       |
| `papaparse`               | CSV input and output        | CSV parsing, header mapping, type conversion, malformed-row reporting, and CSV generation    |

## Selection guidance

- Prefer Recharts for standard charts. Use D3 when the visual needs a layout, projection, or shape
  that Recharts does not provide.
- Prefer Quill's `Table` for small static tables. Use TanStack Table for table behavior and TanStack
  Virtual when the rendered row count is large. These libraries provide behavior, not visual styles.
- Use React Hook Form with Quill inputs. Keep the network submit button disabled while submission is
  active.
- Use Zod at untrusted boundaries, including declared external API responses and parsed CSV rows.
- Use lodash-es named imports so the builder can remove unused helpers.
- React Markdown does not enable raw HTML by default. Do not add plugins or renderers that execute
  HTML from untrusted content.
- Papa Parse processes text already available to the canvas. Loading a remote CSV still requires its
  exact HTTPS origin in `capabilities.network.origins` (published canvases only — the edit-mode
  preview blocks direct network access regardless of declaration).
- Three.js owns its `<canvas>` element. React can own the surrounding Quill application shell.

The standard imports remain `react`, `react-dom`, `react-dom/client`, `@posthog/quill`, `recharts`,
`lucide-react`, and `dayjs`.
