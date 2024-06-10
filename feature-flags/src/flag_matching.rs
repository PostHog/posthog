use crate::flag_definitions::{FeatureFlag, FlagGroupType};
use sha1::{Digest, Sha1};
use std::fmt::Write;

#[derive(Debug, PartialEq, Eq)]
pub struct FeatureFlagMatch {
    pub matches: bool,
    pub variant: Option<String>,
    //reason
    //condition_index
    //payload
}

// TODO: Rework FeatureFlagMatcher - python has a pretty awkward interface, where we pass in all flags, and then again
// the flag to match. I don't think there's any reason anymore to store the flags in the matcher, since we can just
// pass the flag to match directly to the get_match method. This will also make the matcher more stateless.
// Potentially, we could also make the matcher a long-lived object, with caching for group keys and such.
// It just takes in the flag and distinct_id and returns the match...
// Or, make this fully stateless
// and have a separate cache struct for caching group keys, cohort definitions, etc. - and check size, if we can keep it in memory
// for all teams. If not, we can have a LRU cache, or a cache that stores only the most recent N keys.
// But, this can be a future refactor, for now just focusing on getting the basic matcher working, write lots and lots of tests
// and then we can easily refactor stuff around.
#[derive(Debug)]
pub struct FeatureFlagMatcher {
    // pub flags: Vec<FeatureFlag>,
    pub distinct_id: String,
}

const LONG_SCALE: u64 = 0xfffffffffffffff;

impl FeatureFlagMatcher {
    pub fn new(distinct_id: String) -> Self {
        FeatureFlagMatcher {
            // flags,
            distinct_id,
        }
    }

    pub fn get_match(&self, feature_flag: &FeatureFlag) -> FeatureFlagMatch {
        if self.hashed_identifier(feature_flag).is_none() {
            return FeatureFlagMatch {
                matches: false,
                variant: None,
            };
        }

        // TODO: super groups for early access
        // TODO: Variant overrides condition sort

        for (index, condition) in feature_flag.get_conditions().iter().enumerate() {
            let (is_match, _evaluation_reason) =
                self.is_condition_match(feature_flag, condition, index);

            if is_match {
                // TODO: This is a bit awkward, we should handle overrides only when variants exist.
                let variant = match condition.variant.clone() {
                    Some(variant_override) => {
                        if feature_flag
                            .get_variants()
                            .iter()
                            .any(|v| v.key == variant_override)
                        {
                            Some(variant_override)
                        } else {
                            self.get_matching_variant(feature_flag)
                        }
                    }
                    None => self.get_matching_variant(feature_flag),
                };

                // let payload = self.get_matching_payload(is_match, variant, feature_flag);
                return FeatureFlagMatch {
                    matches: true,
                    variant,
                };
            }
        }
        FeatureFlagMatch {
            matches: false,
            variant: None,
        }
    }

    pub fn is_condition_match(
        &self,
        feature_flag: &FeatureFlag,
        condition: &FlagGroupType,
        _index: usize,
    ) -> (bool, String) {
        let rollout_percentage = condition.rollout_percentage.unwrap_or(100.0);
        let mut condition_match = true;
        if condition.properties.is_some() {
            // TODO: Handle matching conditions
            if !condition.properties.as_ref().unwrap().is_empty() {
                condition_match = false;
            }
        }

        if !condition_match {
            return (false, "NO_CONDITION_MATCH".to_string());
        } else if rollout_percentage == 100.0 {
            // TODO: Check floating point schenanigans if any
            return (true, "CONDITION_MATCH".to_string());
        }

        if self.get_hash(feature_flag, "") > (rollout_percentage / 100.0) {
            return (false, "OUT_OF_ROLLOUT_BOUND".to_string());
        }

        (true, "CONDITION_MATCH".to_string())
    }

    pub fn hashed_identifier(&self, feature_flag: &FeatureFlag) -> Option<String> {
        if feature_flag.get_group_type_index().is_none() {
            // TODO: Use hash key overrides for experience continuity
            Some(self.distinct_id.clone())
        } else {
            // TODO: Handle getting group key
            Some("".to_string())
        }
    }

    /// This function takes a identifier and a feature flag key and returns a float between 0 and 1.
    /// Given the same identifier and key, it'll always return the same float. These floats are
    /// uniformly distributed between 0 and 1, so if we want to show this feature to 20% of traffic
    /// we can do _hash(key, identifier) < 0.2
    pub fn get_hash(&self, feature_flag: &FeatureFlag, salt: &str) -> f64 {
        // check if hashed_identifier is None
        let hashed_identifier = self
            .hashed_identifier(feature_flag)
            .expect("hashed_identifier is None when computing hash");
        let hash_key = format!("{}.{}{}", feature_flag.key, hashed_identifier, salt);
        let mut hasher = Sha1::new();
        hasher.update(hash_key.as_bytes());
        let result = hasher.finalize();
        // :TRICKY: Convert the first 15 characters of the digest to a hexadecimal string
        // not sure if this is correct, padding each byte as 2 characters
        let hex_str: String = result.iter().fold(String::new(), |mut acc, byte| {
            let _ = write!(acc, "{:02x}", byte);
            acc
        })[..15]
            .to_string();
        let hash_val = u64::from_str_radix(&hex_str, 16).unwrap();

        hash_val as f64 / LONG_SCALE as f64
    }

    pub fn get_matching_variant(&self, feature_flag: &FeatureFlag) -> Option<String> {
        let hash = self.get_hash(feature_flag, "variant");
        let mut total_percentage = 0.0;

        for variant in feature_flag.get_variants() {
            total_percentage += variant.rollout_percentage / 100.0;
            if hash < total_percentage {
                return Some(variant.key.clone());
            }
        }
        None
    }
}
