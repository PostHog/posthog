# Canvas sidebar

Canvas lists above 40 entries mount the visible rows and four rows of overscan on each side.
Group headers keep their positions in the virtual list, and keyboard indexes follow the displayed group order.
The highlighted option stays mounted when scrolling so Enter can still open it.
Each mounted row states its position in the whole list, because a screen reader can only count what is mounted.
Search and filter changes return the list to the top.

The `Canvases/CanvasList` stories provide small and 1,000-canvas fixtures.
The keyboard story checks Home, End, Enter, filtering, and clearing a search across the virtualization threshold.
Compare mounted option counts and search-clear long tasks at both narrow and wide pane widths.
