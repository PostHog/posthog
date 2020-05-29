export const styles = `
    form { margin-bottom: 0 }
    .form-group { padding: 8px 12px; margin: 0 }
    .form-group.selected { background: rgba(0, 0, 0, 0.1)}
    .form-group:not(:last-child) {border-bottom: 1px solid rgba(0, 0, 0, 0.1) }
    .form-control { font-size: 13px }
    .react-draggable .drag-bar { cursor: grab; margin-bottom: 0.75rem; user-select: none }
    .react-draggable-dragging .drag-bar {cursor: grabbing !important }
    .logo { margin: -7px 15px 0 0; height: 35px }
    .drag-bar h3 { display: inline-block }
    .save-buttons {
        margin: 0 -12px;
        width: calc(100% + 24px);
    }
    .save-buttons .btn { border-radius: 0 }
    .action {
        background: rgba(0, 0, 0, 0.1);
        margin: 0 -12px;
        padding: 6px 12px;
        border-bottom: 1px solid rgba(0, 0, 0, 0.1);
        height: 32px;
    }
    .box {
        touch-action: none;
        position: fixed;
        top: 2rem;
        z-index: 999999999;
        padding: 12px 12px 0 12px;
        right: 2rem;
        overflow-y: scroll;
        width: 300px;
        color: #37352F;
        font-size: 13px;
        max-height: calc(100vh - 4rem);
        box-shadow: rgba(0, 0, 0, 0.4) 0px 0px 13px;
        border-radius: 10px;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif;
        opacity: 1.0;
        transition: opacity ease 0.5s;

        /* effects when content is scrolling */
        background:
            linear-gradient(white 30%, rgba(255,255,255,0)),
            linear-gradient(rgba(255,255,255,0), white 70%) 0 100%,
            radial-gradient(50% 0, farthest-side, rgba(0,0,0,.4), rgba(0,0,0,0)),
            radial-gradient(50% 100%,farthest-side, rgba(0,0,0,.4), rgba(0,0,0,0)) 0 100%;
        background:
            linear-gradient(white 30%, rgba(255,255,255,0)),
            linear-gradient(rgba(255,255,255,0), white 70%) 0 100%,
            radial-gradient(farthest-side at 50% 0, rgba(0,0,0,.4), rgba(0,0,0,0)),
            radial-gradient(farthest-side at 50% 100%, rgba(0,0,0,.4), rgba(0,0,0,0)) 0 100%;
        background-repeat: no-repeat;
        background-color: #f8f9fa;
        background-size: 100% 70px, 100% 70px, 100% 24px, 100% 24px;
        /* Opera doesn't support this in the shorthand */
        background-attachment: local, local, scroll, scroll;
    }
    .box.toolbar-invisible {
        opacity: 0;
    }

    /* form fields */
    label { margin-bottom: 8px }
    input.form-control {
        padding: 8px;
        height: calc(1.5rem + 4px);
    }
    #toolbar {
        --zoom-out: 0.7;
        --padding: 30px;
        --sidebar-width: 300px;
        background-size: 100%;
        transform: scale(calc(1 / var(--zoom-out)));
        transform-origin: top right;
        width: var(--sidebar-width);
        height: calc(100vh - 2 * var(--padding));
        top: 0;
        right: calc((-300px - var(--padding)) / var(--zoom-out));
        position: absolute;
        z-index:999999999;
        box-sizing: border-box;
        opacity: 1.0;
        transition: opacity ease 0.5s;
    }
    #toolbar.toolbar-invisible {
        opacity: 0;
    }
    #toolbar section {
        background: white;
        padding: 20px;
    }
    #toolbar .ant-tabs-bar {
        height: 50px;
        border-bottom: 0;
    }
    #toolbar .ant-tabs-nav-scroll {
        text-align: center;
    }

    #toolbar .float-box {
        background: white;
        padding: 20px;
        box-shadow: hsl(219, 14%, 76%) 30px 30px 70px, hsl(219, 14%, 76%) 8px 8px 10px;
    }
    #toolbar .float-box + .float-box {
        margin-top: 30px;
    }
    #toolbar .float-box.button:hover {
        cursor: pointer;
        box-shadow: hsl(219, 14%, 65%) 30px 30px 70px, hsl(219, 14%, 65%) 8px 8px 10px;
    }
    #toolbar .float-box.button small {
        color: hsla(220, 16%, 49%, 1)
    }

`
