// symbolic panics on some malformed binaries, such as an ELF section that points past the end of
// the file, and posthog-cli stops there. The worker turns the panic into that one file's failure, so
// the other files of a build still upload.

use std::{
    any::Any,
    cell::Cell,
    panic::{self, AssertUnwindSafe},
};

thread_local! {
    static GUARDED: Cell<bool> = const { Cell::new(false) };
}

// A guarded panic is reported as the file's failure, so the default hook stays quiet about it.
pub fn install_hook() {
    let default = panic::take_hook();
    panic::set_hook(Box::new(move |info| {
        if !GUARDED.with(Cell::get) {
            default(info);
        }
    }));
}

pub fn guarded<T>(parse: impl FnOnce() -> Result<T, String>) -> Result<T, String> {
    let outer = GUARDED.with(|guarded| guarded.replace(true));
    let result = panic::catch_unwind(AssertUnwindSafe(parse));
    GUARDED.with(|guarded| guarded.set(outer));

    result.unwrap_or_else(|payload| Err(panic_message(payload.as_ref())))
}

fn panic_message(payload: &(dyn Any + Send)) -> String {
    payload
        .downcast_ref::<&str>()
        .map(|message| message.to_string())
        .or_else(|| payload.downcast_ref::<String>().cloned())
        .unwrap_or_else(|| "the file is malformed".to_string())
}
