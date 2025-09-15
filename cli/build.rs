// Debug token, used to get metrics for debug builds - team 89529
const DEBUG_POSTHOG_API_TOKEN: &str = "phc_raG2H9V246hkNZk6K89DZGG98qQyPrKKlicifGlpOXA";

// This build file just sets this token for debug builds - for production builds, we use the token from our CI's secrets
pub fn main() {
    let profile = std::env::var("PROFILE").expect("Profile variable is set by cargo");
    if profile == "debug" {
        println!("cargo:rustc-env=POSTHOG_API_TOKEN={DEBUG_POSTHOG_API_TOKEN}");
    } else {
        eprintln!("Not setting debug posthog api token");
    }
}
