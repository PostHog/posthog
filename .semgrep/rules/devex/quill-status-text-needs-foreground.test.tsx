// @ts-nocheck

// ruleid: quill-status-text-needs-foreground
const ErrorText = <p className="text-sm text-destructive">{error}</p>

// ruleid: quill-status-text-needs-foreground
const DoneIcon = <CheckCircle2 className="size-4 text-success" />

// ruleid: quill-status-text-needs-foreground
const Conditional = cn('flex', stale ? 'text-warning' : 'text-muted-foreground')

// ruleid: quill-status-text-needs-foreground
const Hover = <span className="hover:text-info" />

// ruleid: quill-status-text-needs-foreground
const Opacity = <span className="text-destructive/80" />

// ruleid: quill-status-text-needs-foreground
const Svg = <path className="stroke-success" />

// ruleid: quill-status-text-needs-foreground
const Completed = <span className="text-completed" />

// ok: quill-status-text-needs-foreground
const Foreground = <p className="text-destructive-foreground">{error}</p>

// ok: quill-status-text-needs-foreground
const Fill = <div className="bg-destructive/5 border-warning" />

// ok: quill-status-text-needs-foreground
const HostVars = { '--color-text-info': '#2563eb' }

// ok: quill-status-text-needs-foreground
const Variant = <Badge variant="destructive">Failed</Badge>
